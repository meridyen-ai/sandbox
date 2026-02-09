"""
REST API for Sandbox

Provides HTTP endpoints for sandbox operations.
Alternative to gRPC for simpler integrations.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, date, timezone
from decimal import Decimal
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Depends, Header, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
import jwt

from sandbox.core.config import get_config
from sandbox.core.exceptions import (
    SandboxError,
    AuthenticationError,
    AuthorizationError,
    ValidationError,
)
from sandbox.core.logging import get_logger, bind_context, clear_context, setup_logging
from sandbox.execution.base import ExecutionContext
from sandbox.execution.sql_executor import SQLExecutor
from sandbox.execution.python_executor import PythonExecutor
from sandbox.visualization.generator import VisualizationGenerator, ChartType

logger = get_logger(__name__)


def _make_json_safe(value: Any) -> Any:
    """Convert non-JSON-serializable values to strings."""
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {k: _make_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_make_json_safe(v) for v in value]
    return value


# =============================================================================
# Request/Response Models
# =============================================================================


class ExecutionContextModel(BaseModel):
    """Execution context from request."""
    request_id: str | None = Field(default_factory=lambda: str(uuid.uuid4()))
    workspace_id: str | None = None
    connection_id: str | None = None
    user_id: str | None = None
    max_rows: int | None = None
    timeout_seconds: int | None = None
    max_memory_mb: int | None = None
    max_output_size_kb: int | None = None


class SQLExecutionRequest(BaseModel):
    """SQL execution request."""
    context: ExecutionContextModel = Field(default_factory=ExecutionContextModel)
    query: str
    parameters: dict[str, Any] | None = None


class PythonExecutionRequest(BaseModel):
    """Python execution request."""
    context: ExecutionContextModel = Field(default_factory=ExecutionContextModel)
    code: str
    input_data: dict[str, Any] | None = None
    variables: dict[str, Any] | None = None


class VisualizationRequest(BaseModel):
    """Visualization request."""
    context: ExecutionContextModel = Field(default_factory=ExecutionContextModel)
    instruction: str | None = None
    data: list[dict[str, Any]]
    chart_type: str = "auto"
    title: str | None = None


class ConnectionConfig(BaseModel):
    """Database connection configuration."""
    id: str | None = None
    name: str
    db_type: str
    host: str
    port: int
    database: str
    username: str
    password: str
    schema_name: str | None = None
    ssl_enabled: bool = True

    @property
    def normalized_db_type(self) -> str:
        """Normalize common db_type aliases to canonical enum values."""
        aliases = {"postgres": "postgresql", "pg": "postgresql", "mssql_server": "mssql"}
        return aliases.get(self.db_type.lower(), self.db_type.lower())


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    uptime_seconds: float
    components: dict[str, dict[str, Any]] | None = None


class CapabilitiesResponse(BaseModel):
    """Capabilities response."""
    sandbox_id: str | None
    version: str
    supported_databases: list[str]
    supported_packages: list[str]
    resource_limits: dict[str, Any]
    supports_streaming: bool
    supports_visualization: bool
    has_local_llm: bool


# =============================================================================
# Dependencies
# =============================================================================


async def verify_sandbox_token(
    authorization: str | None = Header(None, alias="Authorization"),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> dict[str, Any]:
    """
    Verify sandbox authentication token.

    Supports two authentication methods:
    1. Sandbox API Key (sb_*) - Preferred method for user authentication
       - Header: Authorization: Bearer sb_xxx OR X-API-Key: sb_xxx
       - Validates against AI_Assistants_MVP database

    2. JWT Token (legacy) - For platform-to-sandbox communication
       - Header: Authorization: Bearer <jwt_token>
       - Used for internal platform communication

    Returns:
        Dict with workspace_id, user_id, and other context
    """
    from sandbox.auth.sandbox_auth import get_authenticator

    config = get_config()

    # Try X-API-Key header first
    api_key = x_api_key

    # Fall back to Authorization header
    if not api_key and authorization:
        if authorization.startswith("Bearer "):
            api_key = authorization[7:]
        else:
            raise AuthenticationError("Invalid authorization format. Use 'Bearer <token>'")

    if not api_key:
        raise AuthenticationError("Authentication required. Provide X-API-Key or Authorization header")

    # Check if it's a sandbox API key (sb_* prefix)
    if api_key.startswith("sb_"):
        authenticator = get_authenticator()
        if not authenticator:
            raise AuthenticationError("Sandbox authenticator not initialized")

        workspace_context = await authenticator.verify_sandbox_key(api_key)
        if not workspace_context:
            raise AuthenticationError("Invalid or inactive sandbox API key")

        # Return workspace context
        return {
            "auth_type": "sandbox_api_key",
            "workspace_id": str(workspace_context["workspace_id"]),
            "workspace_name": workspace_context["workspace_name"],
            "user_id": str(workspace_context.get("user_id")) if workspace_context.get("user_id") else None,
            "api_key_name": workspace_context["api_key_name"],
            "permissions": workspace_context.get("permissions", {
                "execute_sql": True,
                "execute_python": True,
                "generate_visualizations": True,
            })
        }

    # Otherwise, try to decode as JWT (legacy method for platform communication)
    try:
        secret = config.platform.registration_token
        if secret:
            payload = jwt.decode(
                api_key,
                secret.get_secret_value(),
                algorithms=["HS256"],
                audience="sandbox-executor",
            )
            payload["auth_type"] = "jwt"
            return payload
        else:
            # Development mode - accept any token
            logger.warning("Development mode: accepting token without verification")
            return {
                "auth_type": "dev",
                "workspace_id": "dev",
                "permissions": {}
            }

    except jwt.ExpiredSignatureError:
        raise AuthenticationError("Token expired")
    except jwt.InvalidTokenError as e:
        raise AuthenticationError(f"Invalid token: {e}")


# =============================================================================
# Application Factory
# =============================================================================


def create_rest_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    config = get_config()

    # Lifespan manager
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Startup
        setup_logging()
        logger.info("rest_api_starting", port=config.server.rest_port)

        # Initialize authenticator if API key auth is enabled
        if config.authentication.enable_api_key_auth:
            from sandbox.auth.sandbox_auth import initialize_authenticator
            try:
                initialize_authenticator(
                    config.authentication.mvp_api_url,
                    config.authentication.api_timeout
                )
                logger.info(f"Sandbox API key authentication initialized (MVP API: {config.authentication.mvp_api_url})")
            except Exception as e:
                logger.error(f"Failed to initialize authenticator: {e}")
                if config.environment == "production":
                    raise

        # Initialize executors
        app.state.sql_executor = SQLExecutor()
        app.state.python_executor = PythonExecutor()
        app.state.viz_generator = VisualizationGenerator()
        app.state.start_time = datetime.now(timezone.utc)

        yield

        # Shutdown
        logger.info("rest_api_stopping")
        await app.state.sql_executor.close()

        # Close authenticator
        if config.authentication.enable_api_key_auth:
            from sandbox.auth.sandbox_auth import get_authenticator
            authenticator = get_authenticator()
            if authenticator:
                await authenticator.close()

    app = FastAPI(
        title="Meridyen Sandbox API",
        description="Secure execution sandbox for SQL and Python code",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if config.debug else None,
        redoc_url="/redoc" if config.debug else None,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if config.debug else config.security.allowed_outbound_hosts,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception handlers
    @app.exception_handler(SandboxError)
    async def sandbox_error_handler(request, exc: SandboxError) -> JSONResponse:
        status_code = status.HTTP_400_BAD_REQUEST
        if isinstance(exc, AuthenticationError):
            status_code = status.HTTP_401_UNAUTHORIZED
        elif isinstance(exc, AuthorizationError):
            status_code = status.HTTP_403_FORBIDDEN

        return JSONResponse(
            status_code=status_code,
            content=exc.to_dict(),
        )

    # Routes
    register_routes(app)

    return app


def register_routes(app: FastAPI) -> None:
    """Register API routes."""

    # ==========================================================================
    # Health & Capabilities
    # ==========================================================================

    @app.get("/health", response_model=HealthResponse, tags=["Health"])
    async def health_check(include_details: bool = False) -> HealthResponse:
        """Health check endpoint."""
        uptime = (datetime.now(timezone.utc) - app.state.start_time).total_seconds()

        response = HealthResponse(
            status="healthy",
            version="1.0.0",
            uptime_seconds=uptime,
        )

        if include_details:
            response.components = {
                "sql_executor": {"status": "healthy"},
                "python_executor": {"status": "healthy"},
                "visualization": {"status": "healthy"},
            }

        return response

    @app.get("/capabilities", response_model=CapabilitiesResponse, tags=["Health"])
    async def get_capabilities() -> CapabilitiesResponse:
        """Get sandbox capabilities."""
        from sandbox.connectors.factory import get_available_connectors

        config = get_config()

        return CapabilitiesResponse(
            sandbox_id=config.platform.sandbox_id,
            version="1.0.0",
            supported_databases=get_available_connectors(),
            supported_packages=list(config.security.allowed_python_imports),
            resource_limits={
                "max_memory_mb": config.resource_limits.max_memory_mb,
                "max_cpu_seconds": config.resource_limits.max_cpu_seconds,
                "max_output_size_kb": config.resource_limits.max_output_size_kb,
                "max_rows": config.resource_limits.max_rows,
                "query_timeout_seconds": config.resource_limits.query_timeout_seconds,
                "python_timeout_seconds": config.resource_limits.python_timeout_seconds,
            },
            supports_streaming=True,
            supports_visualization=True,
            has_local_llm=config.local_llm.enabled,
        )

    # ==========================================================================
    # Execution Endpoints
    # ==========================================================================

    @app.post("/api/v1/execute/sql", tags=["Execution"])
    async def execute_sql(
        request: SQLExecutionRequest,
        token_data: dict = Depends(verify_sandbox_token),
    ) -> JSONResponse:
        """Execute SQL query."""
        request_id = request.context.request_id or str(uuid.uuid4())
        bind_context(request_id=request_id)

        try:
            # Build execution context
            exec_context = ExecutionContext(
                request_id=request_id,
                workspace_id=request.context.workspace_id,
                connection_id=request.context.connection_id,
                user_id=request.context.user_id,
                max_rows=request.context.max_rows,
                timeout_seconds=request.context.timeout_seconds,
            )

            # Validate
            errors = await app.state.sql_executor.validate(exec_context, query=request.query)
            if errors:
                raise ValidationError("; ".join(errors))

            # Execute
            result = await app.state.sql_executor.execute(
                exec_context,
                query=request.query,
                parameters=request.parameters,
            )

            return JSONResponse(
                content={
                    "request_id": request_id,
                    "status": "success" if result.is_success() else "error",
                    "data": {
                        "columns": [
                            {"name": c.name, "type": c.data_type, "masked": c.is_masked}
                            for c in result.columns
                        ],
                        "rows": result.rows,
                        "row_count": result.row_count,
                        "total_rows_available": result.total_rows_available,
                    },
                    "metrics": result.metrics.to_dict(),
                }
            )

        except SandboxError:
            raise
        except Exception as e:
            logger.error("execute_sql_error", request_id=request_id, error=str(e))
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            clear_context()

    @app.post("/api/v1/execute/python", tags=["Execution"])
    async def execute_python(
        request: PythonExecutionRequest,
        token_data: dict = Depends(verify_sandbox_token),
    ) -> JSONResponse:
        """Execute Python code."""
        request_id = request.context.request_id or str(uuid.uuid4())
        bind_context(request_id=request_id)

        try:
            exec_context = ExecutionContext(
                request_id=request_id,
                workspace_id=request.context.workspace_id,
                user_id=request.context.user_id,
                timeout_seconds=request.context.timeout_seconds,
                max_memory_mb=request.context.max_memory_mb,
                max_output_size_kb=request.context.max_output_size_kb,
            )

            # Validate
            errors = await app.state.python_executor.validate(exec_context, code=request.code)
            if errors:
                raise ValidationError("; ".join(errors))

            # Build input data
            input_data = {}
            if request.input_data:
                input_data["data"] = request.input_data.get("data", [])
            if request.variables:
                input_data["variables"] = request.variables

            # Execute
            result = await app.state.python_executor.execute(
                exec_context,
                code=request.code,
                input_data=input_data,
            )

            return JSONResponse(
                content={
                    "request_id": request_id,
                    "status": "success" if result.is_success() else "error",
                    "data": {
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "result": result.result_data,
                        "variables": result.variables,
                    },
                    "metrics": result.metrics.to_dict(),
                    "error": result.error_message if not result.is_success() else None,
                }
            )

        except SandboxError:
            raise
        except Exception as e:
            logger.error("execute_python_error", request_id=request_id, error=str(e))
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            clear_context()

    @app.post("/api/v1/visualize", tags=["Visualization"])
    async def create_visualization(
        request: VisualizationRequest,
        token_data: dict = Depends(verify_sandbox_token),
    ) -> JSONResponse:
        """Create visualization from data."""
        request_id = request.context.request_id or str(uuid.uuid4())
        bind_context(request_id=request_id)

        try:
            exec_context = ExecutionContext(
                request_id=request_id,
                workspace_id=request.context.workspace_id,
                max_output_size_kb=request.context.max_output_size_kb,
            )

            # Map chart type
            chart_type_map = {
                "auto": ChartType.AUTO,
                "line": ChartType.LINE,
                "bar": ChartType.BAR,
                "pie": ChartType.PIE,
                "scatter": ChartType.SCATTER,
                "heatmap": ChartType.HEATMAP,
                "table": ChartType.TABLE,
            }
            chart_type = chart_type_map.get(request.chart_type.lower(), ChartType.AUTO)

            # Generate visualization
            result = await app.state.viz_generator.generate(
                exec_context,
                data=request.data,
                instruction=request.instruction,
                chart_type=chart_type,
                title=request.title,
            )

            return JSONResponse(
                content={
                    "request_id": request_id,
                    "status": "success" if result.status.value == "success" else "error",
                    "data": {
                        "plotly_spec": result.plotly_spec,
                        "insight": result.insight,
                        "explanation": result.explanation,
                        "chart_type": result.chart_type.value,
                        "data_points": result.data_points,
                    },
                    "metrics": result.metrics.to_dict(),
                    "error": result.error_message,
                }
            )

        except SandboxError:
            raise
        except Exception as e:
            logger.error("create_visualization_error", request_id=request_id, error=str(e))
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            clear_context()

    # ==========================================================================
    # Handlers (Database Types)
    # ==========================================================================

    @app.get("/api/v1/handlers", tags=["Handlers"])
    async def list_handlers() -> JSONResponse:
        """
        List all available database handlers.

        Returns handler metadata including connection arguments for dynamic form generation.
        """
        from sandbox.services.db_handler_service import DBHandlerService

        handlers = DBHandlerService.get_available_handlers()

        return JSONResponse(content={
            "handlers": [handler.to_dict() for handler in handlers]
        })

    # ==========================================================================
    # Connection Management
    # ==========================================================================

    @app.get("/api/v1/connections", tags=["Connections"])
    async def list_connections(
        token_data: dict = Depends(verify_sandbox_token),
    ) -> JSONResponse:
        """List configured database connections."""
        config = get_config()

        connections = []
        for conn in config.database_connections:
            connections.append({
                "id": conn.id,
                "name": conn.name,
                "db_type": conn.db_type.value,
                "host": conn.host,
                "port": conn.port,
                "database": conn.database,
                "schema": conn.schema_name,
                "is_default": getattr(conn, 'is_default', False),
                "created_at": conn.created_at,
                "updated_at": conn.updated_at,
            })

        return JSONResponse(content={"connections": connections})

    @app.post("/api/v1/connections", tags=["Connections"])
    async def create_connection(
        connection: ConnectionConfig,
        token_data: dict = Depends(verify_sandbox_token),
    ) -> JSONResponse:
        """Create a new database connection."""
        from sandbox.core.config import DatabaseConnectionConfig, DatabaseType, get_config
        from pydantic import SecretStr
        import uuid
        from datetime import datetime, timezone

        config = get_config()

        # Generate ID if not provided
        conn_id = connection.id or str(uuid.uuid4())

        # Create connection config
        now = datetime.now(timezone.utc).isoformat()
        new_conn = DatabaseConnectionConfig(
            id=conn_id,
            name=connection.name,
            db_type=DatabaseType(connection.normalized_db_type),
            host=connection.host,
            port=connection.port,
            database=connection.database,
            username=connection.username,
            password=SecretStr(connection.password),
            schema_name=connection.schema_name,
            ssl_enabled=connection.ssl_enabled,
            created_at=now,
            updated_at=now,
        )

        # Add to config and persist to file
        config.database_connections.append(new_conn)

        from sandbox.core.config import save_persisted_connections
        save_persisted_connections(config)

        return JSONResponse(
            status_code=201,
            content={
                "id": conn_id,
                "name": connection.name,
                "message": "Connection created successfully"
            }
        )

    @app.put("/api/v1/connections/{connection_id}", tags=["Connections"])
    async def update_connection(
        connection_id: str,
        connection: ConnectionConfig,
        token_data: dict = Depends(verify_sandbox_token),
    ) -> JSONResponse:
        """Update an existing database connection."""
        from pydantic import SecretStr
        from datetime import datetime, timezone
        config = get_config()

        # Find and update connection
        for idx, conn in enumerate(config.database_connections):
            if conn.id == connection_id:
                from sandbox.core.config import DatabaseConnectionConfig, DatabaseType

                updated_conn = DatabaseConnectionConfig(
                    id=connection_id,
                    name=connection.name,
                    db_type=DatabaseType(connection.normalized_db_type),
                    host=connection.host,
                    port=connection.port,
                    database=connection.database,
                    username=connection.username,
                    password=SecretStr(connection.password),
                    schema_name=connection.schema_name,
                    ssl_enabled=connection.ssl_enabled,
                    created_at=conn.created_at,
                    updated_at=datetime.now(timezone.utc).isoformat(),
                )
                config.database_connections[idx] = updated_conn

                from sandbox.core.config import save_persisted_connections
                save_persisted_connections(config)

                return JSONResponse(content={
                    "id": connection_id,
                    "message": "Connection updated successfully"
                })

        raise HTTPException(status_code=404, detail="Connection not found")

    @app.delete("/api/v1/connections/{connection_id}", tags=["Connections"])
    async def delete_connection(
        connection_id: str,
        token_data: dict = Depends(verify_sandbox_token),
    ) -> JSONResponse:
        """Delete a database connection."""
        config = get_config()

        # Find and remove connection
        for idx, conn in enumerate(config.database_connections):
            if conn.id == connection_id:
                config.database_connections.pop(idx)

                from sandbox.core.config import save_persisted_connections
                save_persisted_connections(config)

                return JSONResponse(content={
                    "message": "Connection deleted successfully"
                })

        raise HTTPException(status_code=404, detail="Connection not found")

    @app.get("/api/v1/connections/{connection_id}/selected-tables", tags=["Connections"])
    async def get_selected_tables(
        connection_id: str,
        token_data: dict = Depends(verify_sandbox_token),
    ) -> JSONResponse:
        """Get selected tables/columns for a connection."""
        config = get_config()

        for conn in config.database_connections:
            if conn.id == connection_id:
                return JSONResponse(content={
                    "connection_id": connection_id,
                    "selected_tables": conn.selected_tables or {},
                })

        raise HTTPException(status_code=404, detail="Connection not found")

    @app.put("/api/v1/connections/{connection_id}/selected-tables", tags=["Connections"])
    async def save_selected_tables(
        connection_id: str,
        payload: dict,
        token_data: dict = Depends(verify_sandbox_token),
    ) -> JSONResponse:
        """Save selected tables/columns for a connection."""
        from sandbox.core.config import save_persisted_connections
        from datetime import datetime, timezone

        config = get_config()

        for conn in config.database_connections:
            if conn.id == connection_id:
                conn.selected_tables = payload.get("selected_tables", {})
                conn.updated_at = datetime.now(timezone.utc).isoformat()
                save_persisted_connections(config)
                return JSONResponse(content={
                    "connection_id": connection_id,
                    "message": "Selected tables saved successfully",
                    "selected_tables": conn.selected_tables,
                })

        raise HTTPException(status_code=404, detail="Connection not found")

    @app.post("/api/v1/connections/test", tags=["Connections"])
    async def test_connection(
        connection: ConnectionConfig,
        token_data: dict = Depends(verify_sandbox_token),
    ) -> JSONResponse:
        """Test a database connection."""
        from sandbox.connectors.factory import get_connector
        from sandbox.core.config import DatabaseConnectionConfig, DatabaseType
        from pydantic import SecretStr

        try:
            # Build config
            conn_config = DatabaseConnectionConfig(
                id=connection.id,
                name=connection.name,
                db_type=DatabaseType(connection.normalized_db_type),
                host=connection.host,
                port=connection.port,
                database=connection.database,
                username=connection.username,
                password=SecretStr(connection.password),
                schema_name=connection.schema_name,
                ssl_enabled=connection.ssl_enabled,
            )

            # Get connector and test
            connector = get_connector(conn_config.db_type, conn_config)
            conn = await connector.connect()
            is_valid = await connector.test_connection(conn)
            await connector.close_connection(conn)

            return JSONResponse(
                content={
                    "success": is_valid,
                    "message": "Connection successful" if is_valid else "Connection test failed",
                }
            )

        except Exception as e:
            return JSONResponse(
                content={
                    "success": False,
                    "message": str(e),
                }
            )

    # ==========================================================================
    # Schema Sync (for AI Assistants MVP integration)
    # ==========================================================================

    @app.get("/api/v1/schema/sync", tags=["Schema"])
    async def sync_schema(
        connection_id: str,
        include_samples: bool = True,
        sample_limit: int = 10,
        token_data: dict = Depends(verify_sandbox_token),
    ) -> JSONResponse:
        """
        Sync schema from database connection.

        Returns schema with tables, columns, data types, and optional sample data.
        Compatible with AI Assistants MVP schema format.
        """
        from sandbox.connectors.factory import get_connector
        from sandbox.core.config import get_config

        config = get_config()

        # Find connection config
        conn_config = None
        for conn in config.database_connections:
            if conn.id == connection_id:
                conn_config = conn
                break

        if not conn_config:
            raise HTTPException(
                status_code=404,
                detail=f"Connection '{connection_id}' not found"
            )

        try:
            # Get connector
            connector = get_connector(conn_config.db_type, conn_config)

            async with connector.get_connection() as conn:
                # Get all tables
                tables = await connector.get_tables(conn, schema=conn_config.schema_name)

                schema_data = {
                    "connection_id": connection_id,
                    "connection_name": conn_config.name,
                    "database": conn_config.database,
                    "db_type": conn_config.db_type.value,
                    "schema": conn_config.schema_name,
                    "tables": []
                }

                # For each table, get columns and optionally sample data
                for table_name in tables:
                    columns_info = await connector.get_columns(
                        conn,
                        table_name,
                        schema=conn_config.schema_name
                    )

                    table_data = {
                        "name": table_name,
                        "columns": columns_info,
                        "sample_data": None
                    }

                    # Get sample data if requested
                    if include_samples:
                        try:
                            sample_query = f'SELECT * FROM "{table_name}" LIMIT {sample_limit}'
                            if conn_config.schema_name:
                                sample_query = f'SELECT * FROM "{conn_config.schema_name}"."{table_name}" LIMIT {sample_limit}'

                            result = await connector.execute(conn, sample_query)

                            table_data["sample_data"] = {
                                "columns": result.columns,
                                "rows": [
                                    {col: _make_json_safe(val) for col, val in zip(result.columns, row)}
                                    for row in result.rows
                                ],
                                "total_rows": result.row_count
                            }
                        except Exception as e:
                            logger.warning(
                                "failed_to_get_samples",
                                table=table_name,
                                error=str(e)
                            )
                            table_data["sample_data"] = None

                    schema_data["tables"].append(table_data)

                return JSONResponse(content={
                    "status": "success",
                    "data": schema_data
                })

        except Exception as e:
            logger.error("schema_sync_error", connection_id=connection_id, error=str(e))
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/v1/schema/full-sync", tags=["Schema"])
    async def full_sync_schema(
        include_samples: bool = True,
        sample_limit: int = 10,
        token_data: dict = Depends(verify_sandbox_token),
    ) -> JSONResponse:
        """
        Bulk sync: returns all connections with schemas and sample data.

        Used by AI Assistants MVP to pull all connection metadata in one call.
        No credentials are included in the response.
        """
        from sandbox.connectors.factory import get_connector
        from sandbox.core.config import get_config

        config = get_config()
        synced_connections = []

        for conn_config in config.database_connections:
            connection_data = {
                "id": conn_config.id,
                "name": conn_config.name,
                "db_type": conn_config.db_type.value,
                "host": conn_config.host,
                "port": conn_config.port,
                "database": conn_config.database,
                "schema": conn_config.schema_name,
                "is_default": getattr(conn_config, "is_default", False),
                "tables": [],
            }

            # Get selected tables config (if any)
            selected_tables_config = conn_config.selected_tables or {}

            try:
                connector = get_connector(conn_config.db_type, conn_config)

                async with connector.get_connection() as conn:
                    tables = await connector.get_tables(
                        conn, schema=conn_config.schema_name
                    )

                    schema_prefix = conn_config.schema_name or "public"

                    for table_name in tables:
                        # If selected_tables is configured, only sync selected tables
                        if selected_tables_config:
                            full_name = f"{schema_prefix}.{table_name}"
                            table_selection = selected_tables_config.get(full_name)
                            if not table_selection or not table_selection.get("selected"):
                                continue
                            selected_columns = table_selection.get("columns", [])
                        else:
                            selected_columns = None  # Include all columns

                        columns_info = await connector.get_columns(
                            conn, table_name, schema=conn_config.schema_name
                        )

                        # Filter columns if selection exists
                        if selected_columns is not None and selected_columns:
                            columns_info = [
                                col for col in columns_info
                                if col.get("name") in selected_columns
                            ]

                        table_data = {
                            "name": table_name,
                            "columns": columns_info,
                            "sample_data": None,
                        }

                        if include_samples:
                            try:
                                # Build column list for sample query
                                if selected_columns:
                                    col_list = ", ".join(f'"{c}"' for c in selected_columns)
                                else:
                                    col_list = "*"

                                if conn_config.schema_name:
                                    sample_query = f'SELECT {col_list} FROM "{conn_config.schema_name}"."{table_name}" LIMIT {sample_limit}'
                                else:
                                    sample_query = f'SELECT {col_list} FROM "{table_name}" LIMIT {sample_limit}'

                                result = await connector.execute(conn, sample_query)
                                table_data["sample_data"] = {
                                    "columns": result.columns,
                                    "rows": [
                                        {col: _make_json_safe(val) for col, val in zip(result.columns, row)}
                                        for row in result.rows
                                    ],
                                    "total_rows": result.row_count,
                                }
                            except Exception as e:
                                logger.warning(
                                    "full_sync_sample_error",
                                    connection=conn_config.id,
                                    table=table_name,
                                    error=str(e),
                                )

                        connection_data["tables"].append(table_data)

            except Exception as e:
                logger.warning(
                    "full_sync_connection_error",
                    connection=conn_config.id,
                    error=str(e),
                )
                connection_data["error"] = str(e)

            synced_connections.append(connection_data)

        from datetime import datetime, timezone

        return JSONResponse(content={
            "status": "success",
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "connections": synced_connections,
        })

    @app.get("/api/v1/schema/table/{table_name}/samples", tags=["Schema"])
    async def get_table_samples(
        connection_id: str,
        table_name: str,
        limit: int = 10,
        token_data: dict = Depends(verify_sandbox_token),
    ) -> JSONResponse:
        """
        Get sample data from a specific table.

        Compatible with AI Assistants MVP getTableDataSamples() format.
        """
        from sandbox.connectors.factory import get_connector
        from sandbox.core.config import get_config

        config = get_config()

        # Find connection config
        conn_config = None
        for conn in config.database_connections:
            if conn.id == connection_id:
                conn_config = conn
                break

        if not conn_config:
            raise HTTPException(
                status_code=404,
                detail=f"Connection '{connection_id}' not found"
            )

        try:
            connector = get_connector(conn_config.db_type, conn_config)

            async with connector.get_connection() as conn:
                # Build query
                if conn_config.schema_name:
                    query = f'SELECT * FROM "{conn_config.schema_name}"."{table_name}" LIMIT {limit}'
                else:
                    query = f'SELECT * FROM "{table_name}" LIMIT {limit}'

                result = await connector.execute(conn, query)

                return JSONResponse(content={
                    "columns": result.columns,
                    "rows": [
                        {col: _make_json_safe(val) for col, val in zip(result.columns, row)}
                        for row in result.rows
                    ],
                    "total_rows": result.row_count
                })

        except Exception as e:
            logger.error(
                "get_table_samples_error",
                connection_id=connection_id,
                table=table_name,
                error=str(e)
            )
            raise HTTPException(status_code=500, detail=str(e))

    # ==========================================================================
    # Metrics
    # ==========================================================================

    @app.get("/metrics", tags=["Monitoring"])
    async def prometheus_metrics() -> str:
        """Prometheus metrics endpoint."""
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        from starlette.responses import Response

        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )
