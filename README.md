# Meridyen.ai Sandbox Execution Engine

A secure, isolated execution environment for SQL and Python code execution that keeps sensitive data within client infrastructure.

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
- Network access to Meridyen API (for hybrid mode)

### Configuration
```bash
cp config/sandbox.example.yaml config/sandbox.yaml
# Edit sandbox.yaml with your settings
```

### Run
```bash
# Development
make dev

# Production
make prod
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
