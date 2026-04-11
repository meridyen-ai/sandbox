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

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies with pip cache mount — huge speedup for rebuilds
# DEPS_EXTRA controls which DB connectors to install:
#   - "all-databases" (default, full production) — ~8GB venv
#   - "dev-essentials" (postgres+mysql+excel+gsheets) — ~2GB venv, much faster build
ARG DEPS_EXTRA=all-databases
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install --upgrade pip setuptools wheel && \
    pip install ".[${DEPS_EXTRA}]"

# Pre-download spaCy English model (required by Unstructured for hi_res PDF parsing)
# Installs at build time so sandbox user doesn't need write access at runtime
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python -m spacy download en_core_web_sm

# Pre-download faster-whisper small model (avoids runtime download + lock contention)
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8', download_root='/opt/whisper_models')"
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

# FreeTDS configuration for MSSQL connections
# TDS 7.0 avoids TLS handshake issues with certain SQL Server configurations
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
