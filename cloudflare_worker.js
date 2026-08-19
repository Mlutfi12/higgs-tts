/**
 * Cloudflare Worker — relay between OpenAI-compatible clients and RunPod serverless.
 *
 * Client sends:  POST /v1/audio/speech  (same JSON as before)
 * Worker sends:  POST https://api.runpod.ai/v2/{ENDPOINT_ID}/runsync
 * Worker returns: raw MP3 bytes (same as before — client sees no change)
 *
 * Set these in Worker → Settings → Variables:
 *   RUNPOD_API_KEY   — your RunPod API key
 *   RUNPOD_ENDPOINT  — endpoint ID (e.g. "abc123xyz")
 */

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders() });
    }

    if (request.method !== "POST" || !request.url.includes("/v1/audio/speech")) {
      return new Response("Not found", { status: 404 });
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return new Response("Bad JSON", { status: 400 });
    }

    const runpodUrl = `https://api.runpod.ai/v2/${env.RUNPOD_ENDPOINT}/runsync`;

    let resp;
    try {
      resp = await fetch(runpodUrl, {
        method: "POST",
        headers: {
          "Content-Type":  "application/json",
          "Authorization": `Bearer ${env.RUNPOD_API_KEY}`,
        },
        body: JSON.stringify({ input: body }),
      });
    } catch (e) {
      return new Response(`RunPod unreachable: ${e.message}`, { status: 502 });
    }

    if (!resp.ok) {
      const txt = await resp.text();
      return new Response(`RunPod error ${resp.status}: ${txt}`, { status: 502 });
    }

    const result = await resp.json();

    // runsync wraps output in {"id":..., "status":"COMPLETED", "output": {...}}
    const output = result.output ?? result;

    if (output.error) {
      return new Response(`TTS error: ${output.error}`, { status: 500 });
    }

    const audioB64 = output.audio_b64;
    if (!audioB64) {
      return new Response("No audio in response", { status: 500 });
    }

    // Decode base64 → binary
    const binary   = atob(audioB64);
    const bytes    = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

    return new Response(bytes.buffer, {
      status: 200,
      headers: {
        "Content-Type":  "audio/mpeg",
        "Content-Length": bytes.length.toString(),
        ...corsHeaders(),
      },
    });
  },
};

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
  };
}
