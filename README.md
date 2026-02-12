<p align="center">
  <h1 align="center">Meridyen Sandbox</h1>
  <p align="center">Secure, isolated execution engine for SQL and Python code — deployable anywhere.</p>
</p>

<p align="center">
  <a href="https://github.com/meridyen-ai/sandbox/actions/workflows/ci.yml"><img src="https://github.com/meridyen-ai/sandbox/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/meridyen-ai/sandbox/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/version-1.0.0-green" alt="Version">
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
- **Secure Python execution** — RestrictedPython with resource limits and sandboxing
- **SQL injection prevention** — Parameterized queries and query validation
- **Data masking** — Configurable sensitive column masking
- **Three deployment modes** — Cloud, Hybrid (client infra + cloud LLM), Air-gapped (fully on-premise)
- **gRPC + REST APIs** — High-performance communication with the core platform
- **mTLS** — Encrypted sandbox-to-platform communication
- **Web UI** — React-based interface for connection management and dataset browsing
- **Observability** — Prometheus metrics, structured logging, OpenTelemetry tracing

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    CORE PLATFORM (meridyen.ai)                  │
│  • Code Generation (LLM)                                        │
│  • User Management                                              │
│  • Orchestration                                                │
│                              │                                  │
│                    ┌─────────▼─────────┐                       │
│                    │   Task Router     │                       │
│                    └─────────┬─────────┘                       │
└──────────────────────────────┼──────────────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
       ┌──────────┐     ┌──────────┐     ┌──────────┐
       │  Cloud   │     │  Hybrid  │     │Air-Gapped│
       │ Sandbox  │     │ Sandbox  │     │ Sandbox  │
       └──────────┘     └──────────┘     └──────────┘
```

## Quick Start

### Prerequisites

- Docker 24.0+
- Docker Compose 2.0+

### 1. Clone and configure

```bash
git clone https://github.com/meridyen-ai/sandbox.git
cd sandbox
cp config/sandbox.example.yaml config/sandbox.yaml
# Edit sandbox.yaml with your database connections and settings
```

### 2. Run in Hybrid Mode (most common)

```bash
docker compose -f docker-compose.hybrid.yaml up -d
```

### 3. Run with Web UI

```bash
make dev-full
```

Access points:
| Service | URL |
|---------|-----|
| Web UI | http://localhost:5173 |
| REST API | http://localhost:8080 |
| API Docs | http://localhost:8080/docs |
| gRPC | localhost:50051 |
| Metrics | http://localhost:9090/metrics |

### Other Deployment Modes

```bash
# Air-gapped (fully on-premise, includes local LLM)
docker compose -f docker-compose.airgapped.yaml up -d

# Development with hot reload
make dev-full
```

## Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for the full development guide.

```bash
# Quick dev setup
make dev-full          # Docker-based dev with hot reload
make dev-local         # Local dev (no Docker)
make test              # Run tests
make lint              # Lint code
make format            # Auto-format
```

## Project Structure

```
meridyen-sandbox/
├── src/sandbox/           # Python backend
│   ├── auth/              # Authentication (JWT, API keys)
│   ├── connectors/        # Database connectors
│   ├── core/              # Core execution engine
│   ├── execution/         # Python/SQL execution sandboxing
│   ├── handlers/          # Database-specific handlers
│   ├── proto/             # gRPC protocol definitions
│   ├── services/          # REST API and gRPC services
│   └── visualization/     # Chart/visualization generation
├── frontend/              # React + TypeScript web UI
├── config/                # Configuration files
├── tests/                 # Test suite
├── docker-compose.*.yaml  # Deployment configurations
└── Makefile               # Build and dev commands
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

See our [project roadmap](https://github.com/meridyen-ai/sandbox/projects) for planned features.

| Version | Milestone |
|---------|-----------|
| v1.0 | Core execution engine, multi-DB support, hybrid deployment |
| v1.1 | Connection management UI, dataset browser |
| v1.2 | Air-gapped mode with local LLM |
| v2.0 | Plugin system, custom handler SDK |

## License

This project is licensed under the Apache License 2.0 — see the [LICENSE](LICENSE) file for details.

---

<p align="center">
  Built by <a href="https://meridyen.ai">Meridyen.ai</a>
</p>
