<p align="center">
  <h1 align="center">Meridyen Sandbox</h1>
  <p align="center">Secure, isolated execution engine for SQL and Python code — deployable anywhere.</p>
</p>

<p align="center">
  <a href="https://github.com/meridyen-ai/sandbox/actions/workflows/ci.yml"><img src="https://github.com/meridyen-ai/sandbox/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/meridyen-ai/sandbox/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License"></a>
  <a href="https://www.npmjs.com/package/@meridyen/sandbox-client"><img src="https://img.shields.io/npm/v/@meridyen/sandbox-client" alt="npm"></a>
  <a href="https://pypi.org/project/meridyen-sandbox-client/"><img src="https://img.shields.io/pypi/v/meridyen-sandbox-client" alt="PyPI"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
</p>

---

## What is Meridyen Sandbox?

Meridyen Sandbox is a **secure code execution engine** that runs SQL queries and Python scripts in isolated environments. It's designed for AI-powered data platforms where generated code must be executed safely — without exposing sensitive data or infrastructure.

**Key idea:** Keep data execution inside client infrastructure while the AI brain lives in the cloud.

### Why?

- AI agents generate SQL/Python code that needs to run against real databases
- That code must execute **securely** — no data leaks, no injection attacks, no breakouts
- Enterprise clients want execution to stay **on their infrastructure**
- You need multiple deployment modes: cloud, hybrid, and fully air-gapped

## Features

- **Multi-database support** — PostgreSQL, MySQL, MSSQL, Oracle, SAP HANA, ClickHouse, Snowflake, BigQuery, Databricks, Trino, and more
- **Secure Python execution** — RestrictedPython with resource limits and process isolation
- **SQL injection prevention** — Parameterized queries and query validation
- **Data masking** — Configurable sensitive column masking
- **Three deployment modes** — Cloud, Hybrid (client infra + cloud LLM), Air-gapped (fully on-premise)
- **gRPC + REST APIs** — High-performance communication
- **Pluggable authentication** — Static keys, remote HTTP validation, or custom providers
- **Client SDKs** — TypeScript ([npm](https://www.npmjs.com/package/@meridyen/sandbox-client)) and Python ([PyPI](https://pypi.org/project/meridyen-sandbox-client/))
- **Web UI** — React-based interface for connection management and dataset browsing
- **Observability** — Prometheus metrics, structured logging, OpenTelemetry tracing

## Quick Start

### Option 1: Docker (recommended)

```bash
# Pull and run
docker run -d -p 8080:8080 -p 50051:50051 ghcr.io/meridyen-ai/sandbox:latest

# Or clone and configure
git clone https://github.com/meridyen-ai/sandbox.git
cd sandbox
cp config/sandbox.example.yaml config/sandbox.yaml
docker compose -f docker-compose.hybrid.yaml up -d
```

### Option 2: Install with pip

```bash
pip install meridyen-sandbox[postgresql]  # Install with PostgreSQL support
sandbox  # Start the server
```

### Use the Client SDKs

**TypeScript/JavaScript:**
```bash
npm install @meridyen/sandbox-client
```

```typescript
import { SandboxClient } from '@meridyen/sandbox-client'

const client = new SandboxClient({
  baseUrl: 'http://localhost:8080',
  apiKey: 'sb_your-api-key',
})

const result = await client.executeSQL({
  context: { connection_id: 'my-postgres' },
  query: 'SELECT * FROM users LIMIT 10',
})
```

**Python:**
```bash
pip install meridyen-sandbox-client
```

```python
from meridyen_sandbox_client import SandboxClient

async with SandboxClient("http://localhost:8080", api_key="sb_your-key") as client:
    result = await client.execute_sql(
        query="SELECT * FROM users LIMIT 10",
        connection_id="my-postgres",
    )
```

## Authentication

Meridyen Sandbox supports pluggable authentication providers:

| Provider | Use Case | Config |
|----------|----------|--------|
| `static` (default) | Standalone deployments — keys defined in YAML config | `authentication.provider: static` |
| `remote` | Integration with external auth systems via HTTP | `authentication.provider: remote` |
| `noop` | Development only — accepts all requests | `authentication.provider: noop` |

See `config/sandbox.example.yaml` for full configuration examples.

## Access Points

| Service | URL |
|---------|-----|
| REST API | http://localhost:8080 |
| API Docs | http://localhost:8080/docs |
| Web UI | http://localhost:5173 |
| gRPC | localhost:50051 |
| Metrics | http://localhost:9090/metrics |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    YOUR PLATFORM / AI AGENTS                     │
│  • Code Generation (LLM)                                        │
│  • User Management                                              │
│  • Orchestration                                                │
│                              │                                  │
│                    ┌─────────▼─────────┐                       │
│                    │  Client SDK       │                       │
│                    │  (npm / PyPI)     │                       │
│                    └─────────┬─────────┘                       │
└──────────────────────────────┼──────────────────────────────────┘
                               │  REST / gRPC
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
       ┌──────────┐     ┌──────────┐     ┌──────────┐
       │  Cloud   │     │  Hybrid  │     │Air-Gapped│
       │ Sandbox  │     │ Sandbox  │     │ Sandbox  │
       └──────────┘     └──────────┘     └──────────┘
```

## Project Structure

```
meridyen-sandbox/
├── src/sandbox/           # Python backend
│   ├── auth/              # Pluggable authentication providers
│   ├── connectors/        # Database connectors
│   ├── core/              # Configuration, logging, exceptions
│   ├── execution/         # Python/SQL execution sandboxing
│   ├── handlers/          # Database-specific handlers
│   ├── proto/             # gRPC protocol definitions
│   ├── services/          # REST API and gRPC services
│   └── visualization/     # Chart/visualization generation
├── frontend/              # React + TypeScript web UI
├── sdks/                  # Client SDKs
│   ├── typescript/        # @meridyen/sandbox-client (npm)
│   └── python/            # meridyen-sandbox-client (PyPI)
├── config/                # Configuration files
├── tests/                 # Test suite
├── docker-compose.*.yaml  # Deployment configurations
└── Makefile               # Build and dev commands
```

## Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for the full development guide.

```bash
make dev-full          # Docker-based dev with hot reload
make dev-local         # Local dev (no Docker)
make test              # Run tests
make lint              # Lint code
make format            # Auto-format
```

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

Quick links:
- [Good first issues](https://github.com/meridyen-ai/sandbox/labels/good%20first%20issue)
- [Help wanted](https://github.com/meridyen-ai/sandbox/labels/help%20wanted)
- [Development guide](DEVELOPMENT.md)

## Security

For reporting security vulnerabilities, please see [SECURITY.md](SECURITY.md). **Do not open public issues for security bugs.**

## Roadmap

| Version | Milestone |
|---------|-----------|
| v0.9 | Pluggable auth, client SDKs, Docker/PyPI/npm publishing |
| v1.0 | Stable API, comprehensive docs, security audit |
| v1.1 | Plugin system, custom handler SDK |
| v2.0 | WebSocket streaming, multi-language execution |

## License

This project is licensed under the Apache License 2.0 — see the [LICENSE](LICENSE) file for details.

---

<p align="center">
  Built by <a href="https://meridyen.ai">Meridyen.ai</a>
</p>
