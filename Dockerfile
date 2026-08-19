FROM runpod/pytorch:2.4.0-py3.12-cuda12.4.1-devel-ubuntu22.04

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir \
    vllm==0.23.0 \
    vllm-omni==0.23.0rc1 \
    "transformers==5.12.1" \
    fastapi uvicorn httpx numpy \
    runpod

COPY proxy_server.py /app/proxy_server.py
COPY handler.py      /app/handler.py

ENV HF_HOME=/runpod-volume/hf_cache
ENV TRANSFORMERS_CACHE=/runpod-volume/hf_cache

CMD ["python", "-u", "/app/handler.py"]
