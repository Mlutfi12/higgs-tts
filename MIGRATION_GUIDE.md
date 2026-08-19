# Migrate to RunPod Serverless (A40)

## Architecture after migration

```
DumbChat → ibommie-tts.iblooming.ai (Cloudflare Worker)
              ↓
         RunPod Serverless Endpoint (A40, 48GB VRAM)
              ↓ cold start: vllm-omni + proxy logic
              ↓ warm: ~15s per request (same as now)
```

**Cost**: pay per second of GPU time instead of $/hr always-on.  
**Cold start**: ~2–3 min the first time a worker spins up (model download on first run; ~30s after model is cached on network volume).

---

## Files in this folder

| File | Purpose |
|---|---|
| `Dockerfile` | Container image — vllm-omni + proxy + handler |
| `handler.py` | RunPod serverless entrypoint |
| `cloudflare_worker.js` | Relay: OpenAI-format → RunPod API → raw MP3 |

---

## Step 1 — Fix the vllm-omni install source in Dockerfile

Before building, confirm how vllm-omni was installed on the old pod:

```bash
# Start the old pod briefly, SSH in, run:
/runpod-volume/venv/bin/pip show vllm-omni
# Note the "Location:" and "Home-page:" fields
```

If it was installed from a wheel file or private repo, update this line in `Dockerfile`:

```dockerfile
# Default (public GitHub):
"vllm-omni @ git+https://github.com/bosonai/vllm-omni.git"

# If installed from a local wheel:
COPY vllm_omni-*.whl /tmp/
RUN pip install /tmp/vllm_omni-*.whl
```

---

## Step 2 — Build and push Docker image

```bash
cd /Users/l/DumbChat_V3/TTS/serverless

# Copy proxy_server.py into this folder so Docker can COPY it
cp ../proxy_server.py .

# Build (takes 5–15 min first time)
docker build -t yourdockerhubuser/higgs-tts:latest .

# Push
docker login
docker push yourdockerhubuser/higgs-tts:latest
```

---

## Step 3 — Create RunPod Serverless Endpoint

1. Go to **RunPod Console → Serverless → New Endpoint**
2. Settings:
   - **Container image**: `yourdockerhubuser/higgs-tts:latest`
   - **GPU**: `A40` (48GB)
   - **Container disk**: 20 GB
   - **Volume**: attach your existing network volume (has HF cache) — mount at `/runpod-volume`
   - **Min workers**: 0 (scales to zero — no idle cost)
   - **Max workers**: 1 (or 2 for concurrency)
   - **Idle timeout**: 60s (worker stays warm for 60s after last job)
   - **Execution timeout**: 300s
3. Click **Deploy** — note the **Endpoint ID** (looks like `abc1def2ghi3`)

---

## Step 4 — Test the endpoint directly

```bash
curl -X POST https://api.runpod.ai/v2/YOUR_ENDPOINT_ID/runsync \
  -H "Authorization: Bearer YOUR_RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "model": "tts-1",
      "input": "Halo, ini adalah tes suara.",
      "voice": "charma",
      "response_format": "mp3"
    }
  }'
# Should return: {"output": {"audio_b64": "...", "content_type": "audio/mpeg", "size_kb": 42}}
```

---

## Step 5 — Deploy Cloudflare Worker

This keeps `https://ibommie-tts.iblooming.ai/v1/audio/speech` working unchanged.

1. Go to **Cloudflare Dashboard → Workers & Pages → Create**
2. Paste contents of `cloudflare_worker.js`
3. Add **Environment Variables** (Settings → Variables):
   - `RUNPOD_API_KEY` = your RunPod API key
   - `RUNPOD_ENDPOINT` = your endpoint ID from Step 3
4. Deploy

> **Note**: Cloudflare Worker free tier has a 30s CPU time limit. RunPod `runsync` waits up to 300s (the request stays open). Use the **Paid plan ($5/mo)** or route through `run` + `status` polling if you hit timeouts on long texts. For most requests (< 60s generation), free tier is fine.

---

## Step 6 — Update Cloudflare tunnel (remove old pod route)

The old Cloudflare tunnel pointed to the persistent pod. Now the Worker handles everything:

1. Go to **Cloudflare → Zero Trust → Tunnels** → delete or disable the old tunnel
2. Set the `ibommie-tts.iblooming.ai` DNS to point to your Worker route instead:
   - Workers & Pages → your worker → Triggers → Add Custom Domain → `ibommie-tts.iblooming.ai`

---

## Cold start mitigation

Model weights download from HuggingFace on the first cold start (~2–3 min). After that they're in `/runpod-volume/hf_cache` and cold starts drop to ~30s.

To pre-warm: in the RunPod dashboard, set **Min workers = 1** temporarily (costs ~$0.60/hr for A40). Set back to 0 when done.

To pre-bake weights into the image (fastest cold start, larger image ~15GB):

```dockerfile
# Uncomment in Dockerfile:
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('bosonai/higgs-audio-v3-tts-4b')"
```

---

## A40 vs RTX 3090

| | RTX 3090 | A40 |
|---|---|---|
| VRAM | 24 GB | 48 GB |
| `--enforce-eager` needed | yes | no |
| Cost (RunPod) | ~$0.44/hr | ~$0.76/hr |
| Serverless (pay per use) | available | available |

Remove `--enforce-eager` from the `start_vllm()` call in `handler.py` once confirmed working on A40.
