"""Data models for the Meridyen Sandbox client."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutionContext:
    """Context for an execution request."""

    connection_id: str | None = None
    request_id: str | None = None
    workspace_id: str | None = None
    user_id: str | None = None
    max_rows: int = 10000
    timeout_seconds: int = 300

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.connection_id:
            d["connection_id"] = self.connection_id
        if self.request_id:
            d["request_id"] = self.request_id
        if self.workspace_id:
            d["workspace_id"] = self.workspace_id
        if self.user_id:
            d["user_id"] = self.user_id
        d["max_rows"] = self.max_rows
        d["timeout_seconds"] = self.timeout_seconds
        return d


@dataclass
class ExecutionMetrics:
    """Metrics from an execution."""

    duration_ms: float = 0.0
    rows_processed: int = 0
    memory_used_mb: float = 0.0


@dataclass
class SQLExecutionResult:
    """Result of a SQL execution."""

    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    metrics: ExecutionMetrics | None = None
    error: str | None = None

    @property
    def is_success(self) -> bool:
        return self.error is None


@dataclass
class PythonExecutionResult:
    """Result of a Python execution."""

    stdout: str = ""
    stderr: str = ""
    result_data: Any = None
    metrics: ExecutionMetrics | None = None
    error: str | None = None

    @property
    def is_success(self) -> bool:
        return self.error is None


@dataclass
class VisualizationResult:
    """Result of a visualization request."""

    plotly_spec: dict[str, Any] | None = None
    insight: str | None = None
    error: str | None = None

    @property
    def is_success(self) -> bool:
        return self.error is None


@dataclass
class Connection:
    """A database connection."""

    id: str
    name: str
    db_type: str
    host: str
    port: int
    database: str
    schema: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class ConnectionConfig:
    """Configuration for creating/updating a connection."""

    name: str
    db_type: str
    host: str
    port: int
    database: str
    username: str
    password: str
    schema_name: str | None = None
    ssl_enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        d = {
            "name": self.name,
            "db_type": self.db_type,
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "username": self.username,
            "password": self.password,
            "ssl_enabled": self.ssl_enabled,
        }
        if self.schema_name:
            d["schema_name"] = self.schema_name
        return d


@dataclass
class TableColumn:
    """A column in a database table."""

    name: str
    data_type: str
    nullable: bool = True


@dataclass
class TableSampleData:
    """Sample data from a table."""

    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    total_rows: int = 0


@dataclass
class Table:
    """A database table with schema info."""

    name: str
    columns: list[TableColumn] = field(default_factory=list)
    sample_data: TableSampleData | None = None


@dataclass
class SchemaData:
    """Schema metadata from a database connection."""

    connection_id: str
    connection_name: str
    database: str
    db_type: str
    schema: str | None = None
    tables: list[Table] = field(default_factory=list)


@dataclass
class HealthResponse:
    """Health check response."""

    status: str
    version: str
    uptime_seconds: float = 0.0


@dataclass
class CapabilitiesResponse:
    """Sandbox capabilities."""

    supported_databases: list[str] = field(default_factory=list)
    supported_packages: list[str] = field(default_factory=list)
    resource_limits: dict[str, Any] = field(default_factory=dict)
    has_local_llm: bool = False
    sandbox_id: str | None = None
