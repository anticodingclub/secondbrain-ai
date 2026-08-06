# Build from the repo root:
#   docker build -f docker/backend.Dockerfile -t secondbrain-backend .

FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ── Dependencies ────────────────────────────────────────────────────────────
# Copied before the source so a code change does not invalidate the (slow)
# dependency layer.
FROM base AS deps

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefix=/install ".[embeddings-fast]"

# ── Runtime ─────────────────────────────────────────────────────────────────
FROM base AS runtime

# OCR and PDF rasterisation dependencies (Phase 4).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
        poppler-utils \
        tesseract-ocr \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=deps /install /usr/local

# Never run as root: a document parser handling untrusted files is exactly the
# process you want unprivileged.
RUN useradd --create-home --uid 10001 secondbrain
COPY --chown=secondbrain:secondbrain backend/ /app/
COPY --chown=secondbrain:secondbrain docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Uploaded files and the model cache live here, mounted as a volume so they
# survive a rebuild. Created before dropping privileges.
RUN mkdir -p /data/storage /data/models && chown -R secondbrain:secondbrain /data

USER secondbrain

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/v1/health || exit 1

# Migrations run first — see entrypoint.sh.
CMD ["/app/entrypoint.sh"]
