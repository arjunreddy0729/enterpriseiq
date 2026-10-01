# EnterpriseIQ public demo image, for a Hugging Face Docker Space.
#
# The deploy workflow (.github/workflows/deploy.yml) assembles the Space with
# this file as its root Dockerfile, next to copies of backend/ and corpus/.
# Differences from backend/Dockerfile, all forced by the hosting:
#   * the embedding model is downloaded at BUILD time: free Spaces have no
#     persistent disk, so a runtime download would repeat on every cold start;
#   * the corpus is baked in and ingested on startup (INGEST_ON_STARTUP);
#   * it listens on 7860 and ships without dev and parser extras.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/opt/hf-cache \
    CORPUS_DIR=/corpus \
    PORT=7860 \
    ENVIRONMENT=production \
    LOG_FORMAT=json \
    DEMO_MODE=true \
    AUTH_DEV_HEADER_ENABLED=false \
    INGEST_ON_STARTUP=true \
    SEED_ON_STARTUP=true \
    # Hugging Face sits behind one reverse proxy that appends the client IP.
    FORWARDED_PROXY_HOPS=1

WORKDIR /app

# Spaces run the container as uid 1000.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /opt/hf-cache \
    && chown -R appuser:appuser /opt/hf-cache

COPY backend/pyproject.toml ./
# CPU-only torch first; the default Linux wheel pulls ~3.5GB of CUDA.
RUN mkdir -p app && touch app/__init__.py \
    && pip install --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install -e ".[ml]"

COPY --chown=appuser:appuser backend/ ./
COPY --chown=appuser:appuser corpus/ /corpus/
RUN chmod +x scripts/entrypoint.sh

USER appuser
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-base-en-v1.5')"

EXPOSE 7860
CMD ["./scripts/entrypoint.sh"]
