# Meridyen.ai Sandbox Execution Engine

A secure, isolated execution environment for SQL and Python code execution that keeps sensitive data within client infrastructure.

## ✨ New Features

- **🎨 Web UI**: Modern React-based interface for managing connections and viewing datasets
- **🔗 Connection Management**: CRUD operations for database connections
- **📊 Dataset Viewer**: Browse tables, columns, and preview sample data
- **🔄 Schema Sync**: Automatic schema synchronization with AI Assistants MVP
- **🔐 Token-Based Auth**: Secure API authentication with JWT tokens

## Architecture Overview

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

## Deployment Modes

### 1. Cloud-Hosted (Managed by Meridyen)
```bash
# Deployed on Meridyen's infrastructure
# Used for free-tier and clients without self-hosting requirements
```

### 2. Hybrid Mode (Client Infrastructure + Meridyen LLM)
```bash
docker pull meridyen/sandbox:latest
docker-compose -f docker-compose.hybrid.yaml up -d
```

### 3. Air-Gapped Mode (Fully On-Premise)
```bash
docker pull meridyen/sandbox-airgapped:latest
docker-compose -f docker-compose.airgapped.yaml up -d
```

## Quick Start

### Prerequisites
- Docker 24.0+
- Docker Compose 2.0+
- Node.js 18+ and npm (for UI development)
- Network access to Meridyen API (for hybrid mode)

### Configuration
```bash
cp config/sandbox.example.yaml config/sandbox.yaml
# Edit sandbox.yaml with your settings
```

### Run with Web UI

```bash
# Install UI dependencies
make install-ui

# Run backend + UI in development mode
make dev-full

# Or run in production mode with Docker
make run-with-ui
```

Access the sandbox:
- **Web UI**: http://localhost:3000
- **REST API**: http://localhost:8080
- **API Docs**: http://localhost:8080/docs
- **Metrics**: http://localhost:9090/metrics

### Run Backend Only

```bash
# Development
make dev

# Production
make run
```

## Security Features

- **Isolated Python Execution**: RestrictedPython + resource limits
- **SQL Injection Prevention**: Parameterized queries + query validation
- **Data Masking**: Configurable sensitive column masking
- **mTLS Communication**: Encrypted sandbox ↔ platform communication
- **No Data Persistence**: Execution results are ephemeral

## API Documentation

See [docs/api.md](docs/api.md) for full API specification.

## License

Proprietary - Meridyen.ai
