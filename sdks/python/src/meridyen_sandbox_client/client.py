"""
Meridyen Sandbox Client.

Async HTTP client for the Meridyen Sandbox REST API.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from meridyen_sandbox_client.exceptions import (
    SandboxAuthError,
    SandboxConnectionError,
    SandboxError,
    SandboxTimeoutError,
)
from meridyen_sandbox_client.models import (
    CapabilitiesResponse,
    Connection,
    ConnectionConfig,
    ExecutionContext,
    ExecutionMetrics,
    HealthResponse,
    PythonExecutionResult,
    SchemaData,
    SQLExecutionResult,
    Table,
    TableColumn,
    TableSampleData,
    VisualizationResult,
)

logger = logging.getLogger(__name__)


class SandboxClient:
    """
    Async client for the Meridyen Sandbox REST API.

    Usage:
        async with SandboxClient("http://localhost:8080", api_key="sb_xxx") as client:
            result = await client.execute_sql("SELECT 1", connection_id="my-db")
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 60.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._extra_headers = headers or {}
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> SandboxClient:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def connect(self) -> None:
        """Create the HTTP client."""
        request_headers: dict[str, str] = {
            "Content-Type": "application/json",
            **self._extra_headers,
        }
        if self._api_key:
            request_headers["X-API-Key"] = self._api_key

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=request_headers,
            timeout=httpx.Timeout(self._timeout, connect=10.0),
        )
        logger.info(f"Connected to sandbox at {self._base_url}")

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # ========================================================================
    # Health
    # ========================================================================

    async def health(self) -> HealthResponse:
        """Check sandbox health."""
        data = await self._get("/health")
        return HealthResponse(
            status=data.get("status", "unknown"),
            version=data.get("version", ""),
            uptime_seconds=data.get("uptime_seconds", 0.0),
        )

    async def health_check(self) -> bool:
        """Returns True if sandbox is healthy."""
        try:
            h = await self.health()
            return h.status == "healthy"
        except Exception:
            return False

    async def capabilities(self) -> CapabilitiesResponse:
        """Get sandbox capabilities and resource limits."""
        data = await self._get("/capabilities")
        return CapabilitiesResponse(
            supported_databases=data.get("supported_databases", []),
            supported_packages=data.get("supported_packages", []),
            resource_limits=data.get("resource_limits", {}),
            has_local_llm=data.get("has_local_llm", False),
            sandbox_id=data.get("sandbox_id"),
        )

    # ========================================================================
    # Execution
    # ========================================================================

    async def execute_sql(
        self,
        query: str,
        connection_id: str,
        parameters: dict[str, Any] | None = None,
        context: ExecutionContext | None = None,
    ) -> SQLExecutionResult:
        """Execute a SQL query."""
        ctx = context or ExecutionContext(connection_id=connection_id)
        if not ctx.connection_id:
            ctx.connection_id = connection_id

        payload: dict[str, Any] = {
            "context": ctx.to_dict(),
            "query": query,
        }
        if parameters:
            payload["parameters"] = parameters

        data = await self._post("/api/v1/execute/sql", payload)

        metrics = None
        if data.get("metrics"):
            m = data["metrics"]
            metrics = ExecutionMetrics(
                duration_ms=m.get("duration_ms", 0),
                rows_processed=m.get("rows_processed", 0),
                memory_used_mb=m.get("memory_used_mb", 0),
            )

        return SQLExecutionResult(
            columns=data.get("columns", []),
            rows=data.get("rows", []),
            row_count=data.get("row_count", 0),
            metrics=metrics,
            error=data.get("error"),
        )

    async def execute_python(
        self,
        code: str,
        input_data: dict[str, Any] | None = None,
        variables: dict[str, Any] | None = None,
        context: ExecutionContext | None = None,
    ) -> PythonExecutionResult:
        """Execute Python code in the sandbox."""
        ctx = context or ExecutionContext()

        payload: dict[str, Any] = {
            "context": ctx.to_dict(),
            "code": code,
        }
        if input_data:
            payload["input_data"] = input_data
        if variables:
            payload["variables"] = variables

        data = await self._post("/api/v1/execute/python", payload)

        metrics = None
        if data.get("metrics"):
            m = data["metrics"]
            metrics = ExecutionMetrics(
                duration_ms=m.get("duration_ms", 0),
                rows_processed=m.get("rows_processed", 0),
                memory_used_mb=m.get("memory_used_mb", 0),
            )

        return PythonExecutionResult(
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            result_data=data.get("result_data"),
            metrics=metrics,
            error=data.get("error"),
        )

    async def create_visualization(
        self,
        data: list[dict[str, Any]],
        instruction: str,
        chart_type: str = "auto",
        title: str | None = None,
        context: ExecutionContext | None = None,
    ) -> VisualizationResult:
        """Generate a Plotly visualization."""
        ctx = context or ExecutionContext()

        payload: dict[str, Any] = {
            "context": ctx.to_dict(),
            "instruction": instruction,
            "data": data,
            "chart_type": chart_type,
        }
        if title:
            payload["title"] = title

        resp = await self._post("/api/v1/visualize", payload)
        return VisualizationResult(
            plotly_spec=resp.get("plotly_spec"),
            insight=resp.get("insight"),
            error=resp.get("error"),
        )

    # ========================================================================
    # Connections
    # ========================================================================

    async def list_connections(self) -> list[Connection]:
        """List all database connections."""
        data = await self._get("/api/v1/connections")
        return [
            Connection(
                id=c["id"],
                name=c["name"],
                db_type=c["db_type"],
                host=c["host"],
                port=c["port"],
                database=c["database"],
                schema=c.get("schema"),
                created_at=c.get("created_at"),
                updated_at=c.get("updated_at"),
            )
            for c in data.get("connections", [])
        ]

    async def create_connection(self, config: ConnectionConfig) -> dict[str, str]:
        """Create a new connection. Returns {"id": ..., "name": ...}."""
        return await self._post("/api/v1/connections", config.to_dict())

    async def delete_connection(self, connection_id: str) -> None:
        """Delete a connection."""
        await self._delete(f"/api/v1/connections/{connection_id}")

    async def test_connection(self, config: ConnectionConfig) -> dict[str, Any]:
        """Test a connection. Returns {"success": bool, "message": str}."""
        return await self._post("/api/v1/connections/test", config.to_dict())

    # ========================================================================
    # Schema
    # ========================================================================

    async def sync_schema(
        self,
        connection_id: str,
        include_samples: bool = True,
        sample_limit: int = 10,
    ) -> SchemaData:
        """Sync schema metadata from a connection."""
        params = {
            "connection_id": connection_id,
            "include_samples": str(include_samples).lower(),
            "sample_limit": str(sample_limit),
        }
        data = await self._get("/api/v1/schema/sync", params=params)
        raw = data.get("data", data)

        tables = []
        for t in raw.get("tables", []):
            columns = [
                TableColumn(
                    name=c["name"],
                    data_type=c.get("data_type", "unknown"),
                    nullable=c.get("nullable", True),
                )
                for c in t.get("columns", [])
            ]
            sample = None
            if t.get("sample_data"):
                sd = t["sample_data"]
                sample = TableSampleData(
                    columns=sd.get("columns", []),
                    rows=sd.get("rows", []),
                    total_rows=sd.get("total_rows", 0),
                )
            tables.append(Table(name=t["name"], columns=columns, sample_data=sample))

        return SchemaData(
            connection_id=raw.get("connection_id", connection_id),
            connection_name=raw.get("connection_name", ""),
            database=raw.get("database", ""),
            db_type=raw.get("db_type", ""),
            schema=raw.get("schema"),
            tables=tables,
        )

    async def get_table_samples(
        self,
        connection_id: str,
        table_name: str,
        limit: int = 10,
    ) -> TableSampleData:
        """Get sample data from a table."""
        params = {"connection_id": connection_id, "limit": str(limit)}
        data = await self._get(
            f"/api/v1/schema/table/{table_name}/samples", params=params
        )
        return TableSampleData(
            columns=data.get("columns", []),
            rows=data.get("rows", []),
            total_rows=data.get("total_rows", 0),
        )

    # ========================================================================
    # HTTP helpers
    # ========================================================================

    async def _get(
        self, path: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        return await self._request("GET", path, params=params)

    async def _post(self, path: str, body: Any = None) -> dict[str, Any]:
        return await self._request("POST", path, json=body)

    async def _put(self, path: str, body: Any = None) -> dict[str, Any]:
        return await self._request("PUT", path, json=body)

    async def _delete(self, path: str) -> dict[str, Any]:
        return await self._request("DELETE", path)

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, str] | None = None,
        json: Any = None,
    ) -> dict[str, Any]:
        if not self._client:
            await self.connect()
            if not self._client:
                raise SandboxConnectionError()

        try:
            response = await self._client.request(
                method, path, params=params, json=json
            )
        except httpx.TimeoutException as e:
            raise SandboxTimeoutError(str(e)) from e
        except httpx.ConnectError as e:
            raise SandboxConnectionError(str(e)) from e
        except httpx.RequestError as e:
            raise SandboxError(str(e)) from e

        if response.status_code == 401:
            raise SandboxAuthError()

        if response.status_code >= 400:
            try:
                details = response.json()
            except Exception:
                details = response.text
            raise SandboxError(
                f"Request failed: {response.status_code}",
                status_code=response.status_code,
                details=details,
            )

        if response.status_code == 204:
            return {}

        return response.json()
