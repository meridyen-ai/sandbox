"""
Sandbox Configuration Management

Centralized configuration using Pydantic Settings with support for:
- Environment variables
- YAML configuration files
- Default values
- Validation
"""

from __future__ import annotations

import os
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExecutionMode(str, Enum):
    """Sandbox execution mode."""
    CLOUD = "cloud"
    HYBRID = "hybrid"
    AIRGAPPED = "airgapped"


class DatabaseType(str, Enum):
    """Supported database types."""
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    SNOWFLAKE = "snowflake"
    BIGQUERY = "bigquery"
    DATABRICKS = "databricks"
    MSSQL = "mssql"
    ORACLE = "oracle"
    REDSHIFT = "redshift"
    CLICKHOUSE = "clickhouse"


class LogLevel(str, Enum):
    """Log levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class DatabaseConnectionConfig(BaseModel):
    """Configuration for a single database connection."""

    id: str = Field(..., description="Unique connection identifier")
    name: str = Field(..., description="Human-readable connection name")
    db_type: DatabaseType = Field(..., description="Database type")
    host: str = Field(..., description="Database host")
    port: int = Field(..., description="Database port")
    database: str = Field(..., description="Database name")
    username: str = Field(..., description="Database username")
    password: SecretStr = Field(..., description="Database password")
    schema_name: str | None = Field(None, description="Default schema")
    ssl_enabled: bool = Field(True, description="Enable SSL/TLS")
    ssl_ca_cert: str | None = Field(None, description="SSL CA certificate path")
    connection_timeout: int = Field(30, description="Connection timeout in seconds")
    query_timeout: int = Field(300, description="Query timeout in seconds")
    max_pool_size: int = Field(10, description="Maximum connection pool size")
    extra_params: dict[str, Any] = Field(default_factory=dict, description="Extra connection parameters")

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v


class ResourceLimitsConfig(BaseModel):
    """Resource limits for execution."""

    max_memory_mb: int = Field(512, description="Maximum memory in MB", ge=64, le=8192)
    max_cpu_seconds: int = Field(60, description="Maximum CPU time in seconds", ge=1, le=3600)
    max_output_size_kb: int = Field(1024, description="Maximum output size in KB", ge=1, le=102400)
    max_rows: int = Field(100000, description="Maximum rows to return", ge=1, le=10000000)
    max_concurrent_queries: int = Field(10, description="Maximum concurrent queries", ge=1, le=100)
    query_timeout_seconds: int = Field(300, description="Query timeout in seconds", ge=1, le=3600)
    python_timeout_seconds: int = Field(60, description="Python execution timeout", ge=1, le=600)


class SecurityConfig(BaseModel):
    """Security configuration."""

    # Python sandbox settings
    allowed_python_imports: list[str] = Field(
        default_factory=lambda: [
            "json", "math", "datetime", "re", "collections", "itertools", "functools",
            "statistics", "decimal", "fractions", "random", "string", "textwrap",
            "pandas", "numpy", "scipy", "sklearn", "statsmodels", "plotly",
        ],
        description="Allowed Python imports"
    )
    banned_python_patterns: list[str] = Field(
        default_factory=lambda: [
            "exec(", "eval(", "compile(", "__import__", "importlib",
            "open(", "file(", "os.", "sys.", "subprocess", "socket",
            "requests", "urllib", "httpx", "aiohttp",
            "pickle", "marshal", "shelve",
            "ctypes", "cffi", "multiprocessing", "threading",
            "globals(", "locals(", "vars(",
            "getattr(", "setattr(", "delattr(",
            "__builtins__", "__class__", "__bases__", "__subclasses__",
            "__code__", "__globals__", "__dict__",
        ],
        description="Banned Python patterns"
    )

    # SQL security
    allowed_sql_statements: list[str] = Field(
        default_factory=lambda: ["SELECT", "WITH"],
        description="Allowed SQL statement types"
    )
    banned_sql_patterns: list[str] = Field(
        default_factory=lambda: [
            "DROP", "DELETE", "TRUNCATE", "UPDATE", "INSERT", "ALTER", "CREATE",
            "GRANT", "REVOKE", "EXECUTE", "EXEC", "xp_", "sp_",
            "--", "/*", "*/", ";--", "UNION ALL SELECT",
        ],
        description="Banned SQL patterns"
    )

    # Data masking
    sensitive_column_patterns: list[str] = Field(
        default_factory=lambda: [
            "*password*", "*secret*", "*token*", "*key*", "*credential*",
            "*ssn*", "*social_security*", "*credit_card*", "*card_number*",
            "*cvv*", "*pin*", "*account_number*",
        ],
        description="Patterns for sensitive columns to mask"
    )
    mask_sensitive_data: bool = Field(True, description="Enable data masking")

    # Network security
    enable_network_isolation: bool = Field(True, description="Isolate sandbox from network")
    allowed_outbound_hosts: list[str] = Field(
        default_factory=list,
        description="Allowed outbound hosts (if network not isolated)"
    )


class DataSharingConfig(BaseModel):
    """Configuration for data sharing with Core Platform."""

    max_rows_to_platform: int = Field(
        1000, description="Maximum rows to send to platform", ge=0, le=100000
    )
    force_aggregation_threshold: int = Field(
        100, description="Force aggregation if more than N rows", ge=0
    )
    allow_raw_data: bool = Field(
        False, description="Allow sending raw data (vs only aggregated)"
    )
    visualization_mode: str = Field(
        "spec_only", description="Visualization mode: spec_only or with_data"
    )
    max_visualization_data_points: int = Field(
        10000, description="Maximum data points in visualization", ge=100, le=1000000
    )


class PlatformConnectionConfig(BaseModel):
    """Configuration for connecting to Core Platform."""

    platform_url: str = Field(
        "https://api.meridyen.ai",
        description="Core Platform API URL"
    )
    registration_token: SecretStr | None = Field(
        None, description="Registration token for sandbox"
    )
    workspace_id: str | None = Field(None, description="Workspace ID")
    sandbox_id: str | None = Field(None, description="Sandbox ID (auto-generated if not set)")
    heartbeat_interval_seconds: int = Field(30, description="Heartbeat interval", ge=10, le=300)
    reconnect_max_attempts: int = Field(5, description="Max reconnection attempts", ge=1, le=20)
    reconnect_backoff_seconds: int = Field(5, description="Reconnection backoff", ge=1, le=60)

    # mTLS settings
    mtls_enabled: bool = Field(True, description="Enable mTLS")
    client_cert_path: str | None = Field(None, description="Client certificate path")
    client_key_path: str | None = Field(None, description="Client key path")
    ca_cert_path: str | None = Field(None, description="CA certificate path")


class AuthenticationConfig(BaseModel):
    """Configuration for sandbox authentication."""

    mvp_api_url: str = Field(
        "http://localhost:8000",
        description="AI_Assistants_MVP API URL for key validation"
    )
    api_timeout: float = Field(5.0, description="API request timeout in seconds", ge=1.0, le=30.0)
    enable_api_key_auth: bool = Field(True, description="Enable API key authentication")
    allow_jwt_auth: bool = Field(True, description="Allow JWT authentication (legacy)")


class LocalLLMConfig(BaseModel):
    """Configuration for local LLM (air-gapped mode)."""

    enabled: bool = Field(False, description="Enable local LLM")
    provider: str = Field("ollama", description="LLM provider: ollama, vllm, transformers")
    model_name: str = Field("llama3:8b", description="Model name")
    base_url: str = Field("http://localhost:11434", description="LLM API base URL")
    api_key: SecretStr | None = Field(None, description="API key if required")
    max_tokens: int = Field(4096, description="Maximum tokens", ge=256, le=32768)
    temperature: float = Field(0.1, description="Temperature", ge=0.0, le=2.0)


class ServerConfig(BaseModel):
    """Server configuration."""

    host: str = Field("0.0.0.0", description="Server bind host")
    grpc_port: int = Field(50051, description="gRPC server port")
    rest_port: int = Field(8080, description="REST API port")
    metrics_port: int = Field(9090, description="Prometheus metrics port")
    workers: int = Field(4, description="Number of worker processes", ge=1, le=32)
    max_concurrent_requests: int = Field(100, description="Max concurrent requests", ge=1, le=1000)


class SandboxConfig(BaseSettings):
    """
    Main sandbox configuration.

    Configuration is loaded from:
    1. Environment variables (SANDBOX_ prefix)
    2. .env file
    3. YAML config file (if specified)
    4. Default values
    """

    model_config = SettingsConfigDict(
        env_prefix="SANDBOX_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # Basic settings
    environment: str = Field("development", description="Environment: development, staging, production")
    execution_mode: ExecutionMode = Field(ExecutionMode.HYBRID, description="Execution mode")
    log_level: LogLevel = Field(LogLevel.INFO, description="Log level")
    debug: bool = Field(False, description="Enable debug mode")

    # Sub-configurations
    server: ServerConfig = Field(default_factory=ServerConfig)
    resource_limits: ResourceLimitsConfig = Field(default_factory=ResourceLimitsConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    data_sharing: DataSharingConfig = Field(default_factory=DataSharingConfig)
    authentication: AuthenticationConfig = Field(default_factory=AuthenticationConfig)
    platform: PlatformConnectionConfig = Field(default_factory=PlatformConnectionConfig)
    local_llm: LocalLLMConfig = Field(default_factory=LocalLLMConfig)

    # Database connections (loaded from separate config or env)
    database_connections: list[DatabaseConnectionConfig] = Field(
        default_factory=list,
        description="Database connections"
    )

    @classmethod
    def from_yaml(cls, config_path: str | Path) -> "SandboxConfig":
        """Load configuration from YAML file."""
        config_path = Path(config_path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path) as f:
            yaml_config = yaml.safe_load(f)

        # Merge with environment variables (env vars take precedence)
        return cls(**yaml_config)

    def get_connection(self, connection_id: str) -> DatabaseConnectionConfig | None:
        """Get database connection by ID."""
        for conn in self.database_connections:
            if conn.id == connection_id:
                return conn
        return None

    def is_production(self) -> bool:
        """Check if running in production."""
        return self.environment == "production"

    def is_airgapped(self) -> bool:
        """Check if running in air-gapped mode."""
        return self.execution_mode == ExecutionMode.AIRGAPPED


@lru_cache
def get_config() -> SandboxConfig:
    """
    Get cached configuration instance.

    Loads configuration from:
    1. SANDBOX_CONFIG_PATH environment variable (YAML file)
    2. Default locations: ./config/sandbox.yaml, /etc/sandbox/config.yaml
    3. Environment variables
    """
    # Check for explicit config path
    config_path = os.environ.get("SANDBOX_CONFIG_PATH")

    if config_path and Path(config_path).exists():
        return SandboxConfig.from_yaml(config_path)

    # Check default locations
    default_paths = [
        Path("./config/sandbox.yaml"),
        Path("./sandbox.yaml"),
        Path("/etc/sandbox/config.yaml"),
    ]

    for path in default_paths:
        if path.exists():
            return SandboxConfig.from_yaml(path)

    # Fall back to environment variables only
    return SandboxConfig()


def reset_config() -> None:
    """Reset cached configuration (useful for testing)."""
    get_config.cache_clear()
