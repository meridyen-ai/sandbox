# Meridyen Sandbox - Deployment Guide

## Overview

The sandbox runs as two Docker containers: the sandbox application and its dedicated PostgreSQL database.

```
Client request → :8081 REST API (sandbox)
                 :50051 gRPC
                 :9091 Metrics
                 :5433 Upload DB (postgres)
```

Three deployment modes are available:
- **Hybrid** - connects to Meridyen cloud for LLM (most common)
- **Air-gapped** - fully offline with local Ollama LLM
- **Cloud** - runs alongside the MVP platform on a shared Docker network

---

## Hybrid Mode (Standard)

### 1. Clone and configure

```bash
git clone <repo-url> meridyen-sandbox && cd meridyen-sandbox
cp .env.example .env
cp config/sandbox.example.yaml config/sandbox.yaml
```

### 2. Edit `.env`

```bash
SANDBOX_AUTHENTICATION__PROVIDER=static
SANDBOX_AUTH_USERNAME=admin
SANDBOX_AUTH_PASSWORD=<strong-password>
SANDBOX_AUTH_JWT_SECRET=<random-64-char-string>
SANDBOX_REST_PORT=8081
SANDBOX_GRPC_PORT=50051
SANDBOX_METRICS_PORT=9091
```

### 3. Edit `config/sandbox.yaml`

Key sections to configure:

- `execution_mode: hybrid`
- `authentication.static_keys` - set a strong API key
- `platform.platform_url` / `registration_token` / `workspace_id` - Meridyen cloud connection
- `database_connections` - add your database sources
- `resource_limits` - adjust memory/CPU/row limits as needed

### 4. Start

```bash
make run
# or directly:
docker compose -f docker-compose.hybrid.yaml up -d
```

### 5. Verify

```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
curl http://localhost:8081/health
```

---

## Air-Gapped Mode

For environments with no internet access. Runs a local Ollama LLM alongside the sandbox.

### 1. Configure

```bash
cp config/sandbox.example.yaml config/sandbox.yaml
# Set execution_mode: airgapped in sandbox.yaml
```

### 2. Start

```bash
make run-airgapped
# or:
docker compose -f docker-compose.airgapped.yaml up -d
```

This starts three containers: `ollama`, `sandbox`, and an optional `model-loader`. If models aren't pre-downloaded, pull them while online first:

```bash
make download-models
```

---

## Cloud Mode (with MVP Platform)

When running alongside `meridyen-backend` on the same server, the sandbox joins a shared Docker network so the MVP nginx can proxy to it.

### 1. Configure

Sandbox is configured via the MVP's `.env.cloud` file. Key variables:

```
SANDBOX_REST_PORT=8081
MERIDYEN_CLOUD_SANDBOX_URL=http://meridyen-sandbox-dev:8080
SANDBOX_CLOUD_API_KEY=sb_<your-key>
```

### 2. Start (from the MVP repo)

```bash
cd ../meridyen-backend
make cloud-prod-up
```

This starts both MVP and sandbox together.

---

## Update & Restart

### Pull and rebuild

```bash
cd meridyen-sandbox
git pull
make stop
make run
```

Or rebuild the image explicitly:

```bash
docker compose -f docker-compose.hybrid.yaml up -d --build --force-recreate
```

### Restart without rebuilding

```bash
make stop && make run
```

### View logs

```bash
make logs
# or:
docker logs -f meridyen-sandbox
```

---

## Environment Variables Reference

All settings in `sandbox.yaml` can be overridden with env vars using the pattern `SANDBOX_SECTION__KEY`.

| Variable | Default | Purpose |
|---|---|---|
| `SANDBOX_REST_PORT` | 8081 | Host port for REST API |
| `SANDBOX_GRPC_PORT` | 50051 | Host port for gRPC |
| `SANDBOX_METRICS_PORT` | 9091 | Host port for Prometheus metrics |
| `SANDBOX_PG_PORT` | 5433 | Host port for upload database |
| `SANDBOX_EXECUTION_MODE` | hybrid | hybrid / airgapped |
| `SANDBOX_AUTHENTICATION__PROVIDER` | static | static / remote / noop |
| `SANDBOX_AUTH_USERNAME` | admin | Web UI login |
| `SANDBOX_AUTH_PASSWORD` | admin123 | Web UI password |
| `SANDBOX_CPU_LIMIT` | 2 | Container CPU limit |
| `SANDBOX_MEMORY_LIMIT` | 2G | Container memory limit |
| `MAX_MEMORY_MB` | 512 | Per-execution memory limit |
| `MAX_CPU_SECONDS` | 60 | Per-execution CPU time limit |
| `MAX_ROWS` | 100000 | Max rows returned per query |

## Makefile Reference

| Command | What it does |
|---|---|
| `make run` | Start hybrid mode (detached) |
| `make run-airgapped` | Start air-gapped mode |
| `make stop` | Stop all sandbox containers |
| `make logs` | Tail sandbox logs |
| `make build` | Build production image |
| `make health` | Check health endpoint |
| `make clean` | Remove containers and volumes |
| `make clean-all` | Remove everything including images |
