# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.9.0] - 2026-02-16

### Added
- **Pluggable authentication** — new `AuthProvider` interface with three built-in providers:
  - `StaticKeyAuthProvider` — validate API keys from YAML config (default)
  - `RemoteAuthProvider` — validate via external HTTP endpoint
  - `NoopAuthProvider` — accept all requests (development only)
- **TypeScript SDK** (`@meridyen/sandbox-client`) — zero-dependency npm package
- **Python SDK** (`meridyen-sandbox-client`) — async httpx-based PyPI package
- **Docker image publishing** — GitHub Actions workflow for GHCR
- **PyPI publishing** — GitHub Actions workflow with trusted publishing
- **npm publishing** — GitHub Actions workflow for TypeScript SDK
- `.env.example` for easier onboarding
- `[project.urls]` in pyproject.toml for PyPI metadata
- Optional database driver extras in pyproject.toml (`pip install meridyen-sandbox[postgresql]`)

### Changed
- **BREAKING:** Authentication config restructured — `mvp_api_url` replaced with `provider` + `remote_url`
  - Old: `authentication.mvp_api_url: "http://..."` + `authentication.api_timeout: 5.0`
  - New: `authentication.provider: remote` + `authentication.remote_url: "http://..."` + `authentication.remote_timeout: 5.0`
  - For standalone use: `authentication.provider: static` with `authentication.static_keys: [...]`
- **BREAKING:** Embed bridge message prefix changed from `mvp:` to `host:` (`host:init`, `host:navigate`, `host:theme-changed`)
- **BREAKING:** Environment variable `SANDBOX_MVP_API_URL` replaced with `SANDBOX_AUTHENTICATION__REMOTE_URL` and `SANDBOX_AUTHENTICATION__PROVIDER`
- Database drivers moved to optional extras to reduce default install size
- Version changed from 1.0.0 to 0.9.0 (pre-stable API)
- Architecture diagram updated to show client SDK integration pattern

### Removed
- All references to AI_Assistants_MVP — sandbox is now fully standalone
- `SandboxAuthenticator` class (replaced by `AuthProvider` interface)

### Migration Guide

**From 1.0.0 to 0.9.0:**

1. Update authentication config:
   ```yaml
   # Before
   authentication:
     mvp_api_url: "http://localhost:8000"
     api_timeout: 5.0

   # After (standalone)
   authentication:
     provider: static
     static_keys:
       - key: "sb_your-key"
         workspace_id: "default"

   # After (with external auth service)
   authentication:
     provider: remote
     remote_url: "http://localhost:8000/api/v1/sandbox/validate-key"
     remote_timeout: 5.0
   ```

2. Update environment variables:
   ```bash
   # Before
   SANDBOX_MVP_API_URL=http://host.docker.internal:18000

   # After
   SANDBOX_AUTHENTICATION__PROVIDER=remote
   SANDBOX_AUTHENTICATION__REMOTE_URL=http://host.docker.internal:18000/api/v1/sandbox/validate-key
   ```

3. Update embed bridge message handlers (if using iframe embed):
   ```javascript
   // Before: 'mvp:init', 'mvp:navigate', 'mvp:theme-changed'
   // After:  'host:init', 'host:navigate', 'host:theme-changed'
   ```

## [1.0.0] - 2025-02-09

### Added
- Core secure execution engine for SQL and Python
- Database connectors: PostgreSQL, MySQL, MSSQL, Oracle, SAP HANA, ClickHouse, Snowflake, BigQuery, Databricks, Trino
- RestrictedPython sandbox for safe Python execution
- SQL injection prevention with parameterized queries
- Configurable data masking for sensitive columns
- Three deployment modes: Cloud, Hybrid, Air-gapped
- gRPC and REST API interfaces
- mTLS support for secure communication
- React + TypeScript web UI for connection management
- Prometheus metrics and structured logging
- API key and JWT authentication
- Docker Compose configurations for all deployment modes
- Internationalization (i18n) with English translations
- Architecture visualization in frontend
- Open-source project foundation (LICENSE, CONTRIBUTING, CODE_OF_CONDUCT)
- GitHub issue and PR templates
- CI workflow with GitHub Actions
- Security policy (SECURITY.md)

[Unreleased]: https://github.com/meridyen-ai/sandbox/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/meridyen-ai/sandbox/compare/v1.0.0...v0.9.0
[1.0.0]: https://github.com/meridyen-ai/sandbox/releases/tag/v1.0.0
