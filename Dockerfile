# VideoWiki / VideoMind - FastAPI production image
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/opt/hf-cache \
    WHISPER_MODEL=base \
    DATA_DIR=/data \
    DATABASE_URL=sqlite:////data/videomind.db \
    UPLOAD_FOLDER=/data/uploads \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app

# Install dependencies first for better layer caching
COPY videomind/requirements.txt .
RUN pip install -r requirements.txt

# Bake the Whisper model into the image so the first upload does not need to download it.
# Build with --build-arg PRELOAD_WHISPER=false to skip (model is then downloaded on first use).
ARG PRELOAD_WHISPER=true
RUN if [ "$PRELOAD_WHISPER" = "true" ]; then \
      python -c "import os; from faster_whisper.utils import download_model; download_model(os.environ['WHISPER_MODEL'])"; \
    fi

COPY videomind/ .

# Run as an unprivileged user; /data holds the SQLite DB and temporary uploads
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data/uploads /opt/hf-cache \
    && chown -R appuser:appuser /data /opt/hf-cache
USER appuser

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8000'), timeout=4)" || exit 1

# Single worker on purpose: ingest progress queues live in process memory.
CMD ["sh", "-c", "exec uvicorn app:app --host \"$HOST\" --port \"$PORT\" --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
