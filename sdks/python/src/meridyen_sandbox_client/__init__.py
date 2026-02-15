"""
Meridyen Sandbox Client — Python SDK for the Meridyen Sandbox execution engine.

Usage:
    from meridyen_sandbox_client import SandboxClient

    async with SandboxClient("http://localhost:8080", api_key="sb_xxx") as client:
        result = await client.execute_sql(
            query="SELECT * FROM users LIMIT 10",
            connection_id="my-postgres",
        )
        print(result.columns, result.rows)
"""

from meridyen_sandbox_client.client import SandboxClient
from meridyen_sandbox_client.models import (
    ExecutionContext,
    ExecutionMetrics,
    SQLExecutionResult,
    PythonExecutionResult,
    VisualizationResult,
    Connection,
    ConnectionConfig,
    SchemaData,
    TableSampleData,
    HealthResponse,
    CapabilitiesResponse,
)
from meridyen_sandbox_client.exceptions import (
    SandboxError,
    SandboxAuthError,
    SandboxTimeoutError,
    SandboxConnectionError,
)

__version__ = "0.9.0"

__all__ = [
    "SandboxClient",
    "ExecutionContext",
    "ExecutionMetrics",
    "SQLExecutionResult",
    "PythonExecutionResult",
    "VisualizationResult",
    "Connection",
    "ConnectionConfig",
    "SchemaData",
    "TableSampleData",
    "HealthResponse",
    "CapabilitiesResponse",
    "SandboxError",
    "SandboxAuthError",
    "SandboxTimeoutError",
    "SandboxConnectionError",
]
