# EnterpriseIQ API image.
#
# The ML extras (torch, sentence-transformers) take the image from ~540MB to
# ~2.5GB. That is the price of local embeddings, and it buys the ability to
# re-embed the corpus as many times as tuning requires at zero marginal cost.
# Model weights themselves live on the hfcache volume, not in the image.

# Pinned to 3.13 to match the local development venv exactly. Dev/prod Python
# drift is cheap to prevent and expensive to debug once benchmark numbers are
# involved: embeddings and reranker scores are what the evaluation harness
# measures, and "it scored differently on my laptop" is not an answer.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Model weights live on a named volume so rebuilds do not re-download them.
    HF_HOME=/opt/hf-cache

WORKDIR /app

# curl is used by the compose healthcheck. psycopg[binary] ships wheels, so we
# need no compiler and no libpq-dev.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root runtime user.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /opt/hf-cache \
    && chown -R appuser:appuser /opt/hf-cache

# --- Dependency layer ------------------------------------------------------
# Copy only the manifest, create a stub package so the editable install
# succeeds, then install. This layer is cached and only re-runs when
# pyproject.toml changes - not on every source edit.
COPY pyproject.toml ./
# Install the CPU-only torch build FIRST, from PyTorch's cpu index.
#
# `pip install torch` on linux/amd64 defaults to the CUDA build and drags in
# ~2.9GB of nvidia-* wheels plus ~650MB of triton - GPU kernels that can never
# execute in this image. Pinning the cpu index first means the ml extra sees
# torch already satisfied and leaves it alone. Image: ~8.9GB -> ~2.5GB.
RUN mkdir -p app && touch app/__init__.py \
    && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install --no-cache-dir -e ".[ml,parsers,dev]"

# --- Source layer ----------------------------------------------------------
COPY . .

RUN chmod +x scripts/entrypoint.sh && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# The entrypoint waits for Postgres, runs migrations, seeds identities, then
# starts uvicorn. See scripts/entrypoint.sh.
CMD ["./scripts/entrypoint.sh"]
