"""
RunPod serverless handler for Higgs Audio V3 TTS.

Startup (once per worker): launches vllm-omni, waits for ready.
Handler: runs proxy logic, returns base64-encoded MP3.

Input JSON:  same as OpenAI /v1/audio/speech
Output JSON: {"audio_b64": "...", "content_type": "audio/mpeg"}
"""

import os
import sys
import time
import subprocess
import httpx
import runpod

# ── Add proxy helpers to path ─────────────────────────────────────────────────
sys.path.insert(0, "/app")
from proxy_server import (
    split_into_chunks,
    assemble_chunks,
    wav_to_mp3,
    _load_charma,
    _charma_ref_audio,
    CHARMA_REF_TEXT,
    log,
)
import asyncio, base64

HIGGS_URL = "http://localhost:8007/v1/audio/speech"
MODEL_ID  = "bosonai/higgs-audio-v3-tts-4b"


# ── Start vllm-omni once per worker ──────────────────────────────────────────

def start_vllm():
    cmd = [
        "vllm-omni", "serve", MODEL_ID,
        "--omni",
        "--port", "8007",
        "--host", "127.0.0.1",
        "--stage-init-timeout", "1800",
        "--gpu-memory-utilization", "0.85",   # 0.65 on RTX 3090; A40 has 48GB so 0.85 is safe
        "--max-model-len", "32768",
        "--dtype", "bfloat16",
        # --enforce-eager not needed on A40
    ]
    log.info("Starting vllm-omni...")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc


def wait_for_vllm(timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get("http://localhost:8007/health", timeout=3)
            if r.status_code == 200:
                log.info("vllm-omni ready")
                return True
        except Exception:
            pass
        time.sleep(3)
    raise RuntimeError("vllm-omni did not become ready in time")


log.info("Worker startup — launching vllm-omni")
_vllm_proc = start_vllm()
wait_for_vllm()
_load_charma()
log.info("Worker ready")


# ── Handler ───────────────────────────────────────────────────────────────────

async def _run_tts(body: dict) -> bytes:
    text   = body.get("input", "")
    chunks = split_into_chunks(text)
    log.info(f"request: {len(text)} chars → {len(chunks)} chunk(s)")

    base = {k: v for k, v in body.items() if k != "input"}
    base["model"]           = MODEL_ID
    base["response_format"] = "wav"
    base["seed"]            = 42
    base["temperature"]     = base.get("temperature", 0.8)
    base["top_k"]           = base.get("top_k", 20)
    base["emotion"]         = base.get("emotion", "neutral")
    base["expressiveness"]  = base.get("expressiveness", 0.3)
    base["speed"]           = base.get("speed", 1.0)

    if base.get("voice") in ("ref_voice", "charma") and "ref_audio" not in base:
        if _charma_ref_audio:
            base["ref_audio"] = _charma_ref_audio
            base["ref_text"]  = CHARMA_REF_TEXT
        else:
            base.pop("voice", None)

    async def gen_one(chunk_text, idx):
        payload = {**base, "input": chunk_text,
                   "max_new_tokens": max(2000, int(len(chunk_text) * 0.065 * 25 * 8 * 1.5))}
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=300) as client:
                    r = await client.post(HIGGS_URL, json=payload)
                if r.status_code == 200:
                    return r.content
                log.warning(f"chunk[{idx}] HTTP {r.status_code} attempt {attempt+1}")
            except Exception as e:
                log.warning(f"chunk[{idx}] error attempt {attempt+1}: {e}")
            if attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))
        return None

    results  = await asyncio.gather(*[gen_one(c, i) for i, c in enumerate(chunks)])
    good     = [r for r in results if r]
    merged   = assemble_chunks(good)
    return wav_to_mp3(merged)


def handler(job):
    body = job.get("input", {})
    try:
        mp3 = asyncio.run(_run_tts(body))
        return {
            "audio_b64":    base64.b64encode(mp3).decode(),
            "content_type": "audio/mpeg",
            "size_kb":      len(mp3) // 1024,
        }
    except Exception as e:
        log.error(f"handler error: {e}")
        return {"error": str(e)}


runpod.serverless.start({"handler": handler})
