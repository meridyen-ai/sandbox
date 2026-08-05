# syntax=docker/dockerfile:1.6
# =============================================================================
# Meridyen Sandbox Container
# =============================================================================
# Multi-stage build for minimal, secure production image
#
# Usage:
#   DOCKER_BUILDKIT=1 docker build -t meridyen/sandbox:latest .
#   docker run -p 8080:8080 -p 50051:50051 meridyen/sandbox:latest

# -----------------------------------------------------------------------------
# Stage 1: Builder
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS builder

# Install build dependencies with apt cache mounts (persists across rebuilds)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    # PostgreSQL
    libpq-dev \
    # MySQL
    default-libmysqlclient-dev \
    # MSSQL
    freetds-dev \
    # ODBC
    unixodbc-dev \
    # SSL
    libssl-dev \
    # Unstructured document processing dependencies
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    libmagic1 \
    pandoc \
    # Audio/Video processing
    ffmpeg

WORKDIR /build

# Copy only requirements first for better caching
COPY pyproject.toml ./
COPY README.md ./
COPY src/sandbox/__init__.py src/sandbox/

# Install uv — a rust-based pip replacement that resolves dependencies ~50x faster.
# pip's resolver spends 10+ minutes backtracking on the unstructured+llama-index+torch
# dependency graph. uv resolves the same graph in ~15 seconds.
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install --upgrade pip uv

# Create virtual environment using uv (drop-in for python -m venv)
RUN uv venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    VIRTUAL_ENV=/opt/venv \
    UV_LINK_MODE=copy

# Install CPU-only torch BEFORE unstructured — otherwise unstructured[image] will pull
# the default GPU torch wheel, which drags in ~6GB of nvidia-*-cu12 CUDA libraries that
# we don't need (sandbox runs CPU-only inference). Pinning CPU torch first makes
# unstructured+detectron2 reuse it via uv's resolver.
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv pip install --index-strategy unsafe-best-match \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        "torch>=2.1.0" "torchvision>=0.16.0"

# Install Python dependencies with uv. The uv cache mount replaces pip's cache.
# DEPS_EXTRA controls which DB connectors to install:
#   - "all-databases" (default, full production) — ~8GB venv
#   - "dev-essentials" (postgres+mysql+excel+gsheets) — ~2GB venv, much faster build
ARG DEPS_EXTRA=all-databases
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv pip install --index-strategy unsafe-best-match \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        ".[${DEPS_EXTRA}]"

# Remove pymupdf_layout, which uv pulls in as a pymupdf4llm dependency.
# It is OPTIONAL (it only offers "improved page layout analysis") and actively
# harmful here on two counts:
#   1. Its files install INSIDE the pymupdf package dir (pymupdf/layout, _tgif.so,
#      _features.so) and can overwrite it, deleting `fitz` — PDF indexing then
#      fails with ModuleNotFoundError while the container still reports healthy.
#   2. It hijacks pymupdf4llm.to_markdown into rasterise+Tesseract OCR mode even
#      for PDFs that HAVE a text layer. With the eng-only traineddata in this
#      image that turns Arabic documents into Latin mojibake, replacing a
#      perfectly good text layer with garbage.
# Keep this immediately after the dependency install so it can never ship.
RUN SP="$(python -c 'import site; print(site.getsitepackages()[0])')" && \
    rm -rf "$SP/pymupdf_layout" "$SP"/pymupdf_layout-*.dist-info \
           "$SP/pymupdf/layout" "$SP/pymupdf/tgif.py" \
           "$SP/pymupdf/_tgif.so" "$SP/pymupdf/_features.so" && \
    python -c "import fitz, pymupdf4llm; print('pymupdf OK', fitz.version[0])"

# Pre-download spaCy English model (required by Unstructured for hi_res PDF parsing)
# Installs at build time so sandbox user doesn't need write access at runtime
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python -m spacy download en_core_web_sm

# Pre-download faster-whisper small model (avoids runtime download + lock contention)
# Cache mount stores the HuggingFace hub download so rebuilds don't re-fetch 500MB.
RUN --mount=type=cache,target=/root/.cache/huggingface,sharing=locked \
    python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8', download_root='/opt/whisper_models')"
ENV WHISPER_MODEL_PATH=/opt/whisper_models

# -----------------------------------------------------------------------------
# Stage 2: Production Runtime
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Labels
LABEL org.opencontainers.image.title="Meridyen Sandbox"
LABEL org.opencontainers.image.description="Secure execution sandbox for SQL and Python"
LABEL org.opencontainers.image.vendor="Meridyen.ai"
LABEL org.opencontainers.image.version="1.0.0"

# Install runtime dependencies with apt cache mounts
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && apt-get install -y --no-install-recommends \
    # PostgreSQL client
    libpq5 \
    # MySQL client
    default-mysql-client \
    # MSSQL client
    libct4 \
    # ODBC runtime
    unixodbc \
    # Process utils
    procps \
    # Healthcheck
    curl \
    # Security: CA certificates
    ca-certificates \
    # Unstructured document processing: OCR + PDF rendering
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    libmagic1 \
    pandoc \
    # Audio/Video processing
    ffmpeg

# FreeTDS configuration for MSSQL connections.
# 7.0 is only the floor for tools that read this file (tsql, ODBC) — it avoids TLS
# handshake issues with certain SQL Server configurations. The app itself negotiates
# per connection in sandbox/connectors/mssql_tds.py (7.4 first, falling back to 7.0),
# because 7.0 carries no column collation and mangles non-Latin-1 text.
RUN printf '[global]\ntds version = 7.0\nencryption = off\nclient charset = UTF-8\ntext size = 64512\n' \
    > /etc/freetds/freetds.conf

# Security: Create non-root user
ARG APP_UID=1000
ARG APP_GID=1000

RUN groupadd --gid ${APP_GID} sandbox && \
    useradd --uid ${APP_UID} --gid sandbox --create-home --shell /bin/bash sandbox

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
# Copy pre-downloaded whisper models to avoid runtime download race conditions
COPY --from=builder /opt/whisper_models /opt/whisper_models
ENV WHISPER_MODEL_PATH=/opt/whisper_models
ENV PATH="/opt/venv/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy application code
COPY --chown=sandbox:sandbox src/sandbox /app/sandbox
COPY --chown=sandbox:sandbox config /app/config

# Create necessary directories
RUN mkdir -p /app/logs /app/data && \
    chown -R sandbox:sandbox /app

# Security: Remove write permissions from code
RUN chmod -R 555 /app/sandbox

# Switch to non-root user
USER sandbox

# Environment variables
ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Sandbox config
    SANDBOX_ENVIRONMENT=production \
    SANDBOX_SERVER__HOST=0.0.0.0 \
    SANDBOX_SERVER__REST_PORT=8080 \
    SANDBOX_SERVER__GRPC_PORT=50051

# Expose ports
EXPOSE 8080 50051 9090

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Entry point
ENTRYPOINT ["python", "-m", "sandbox.main"]

# -----------------------------------------------------------------------------
# Stage 3: Development (optional)
# -----------------------------------------------------------------------------
FROM runtime AS development

USER root

# Install development dependencies with pip cache mount
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install \
    pytest \
    pytest-asyncio \
    pytest-cov \
    mypy \
    ruff \
    black

# Re-enable write permissions for hot reload
RUN chmod -R 755 /app/sandbox

USER sandbox

ENV SANDBOX_ENVIRONMENT=development \
    SANDBOX_DEBUG=true

CMD ["python", "-m", "sandbox.main"]
