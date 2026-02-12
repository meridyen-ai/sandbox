# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Open-source project foundation (LICENSE, CONTRIBUTING, CODE_OF_CONDUCT)
- GitHub issue and PR templates
- CI workflow with GitHub Actions
- Security policy (SECURITY.md)

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

[Unreleased]: https://github.com/meridyen-ai/sandbox/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/meridyen-ai/sandbox/releases/tag/v1.0.0
