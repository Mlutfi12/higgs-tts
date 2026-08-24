FROM pytorch/pytorch:2.4.0-cuda12.4-cudnn9-devel

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

ENV HF_HOME=/tmp/hf_cache
ENV TRANSFORMERS_CACHE=/tmp/hf_cache
ENV HF_HUB_DISABLE_XET=1

CMD ["python", "-u", "/app/handler.py"]
