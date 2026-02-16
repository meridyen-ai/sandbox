"""
REST API for Sandbox

Provides HTTP endpoints for sandbox operations.
Alternative to gRPC for simpler integrations.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, date, time, timedelta, timezone
from decimal import Decimal
from enum import Enum
from ipaddress import IPv4Address, IPv6Address, IPv4Network, IPv6Network
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import UUID

from fastapi import FastAPI, File, Form, HTTPException, Depends, Header, UploadFile, status
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
    """Convert any database value to a JSON-serializable type.

    Handles types from all supported databases (PostgreSQL, MySQL, MSSQL,
    Snowflake, BigQuery, etc.) so the API response is database-agnostic.
    """
    if value is None:
        return None
    # Primitives — fast path
    if isinstance(value, (bool, int, float, str)):
        return value
    # Date/time types (all databases)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    # Numeric types
    if isinstance(value, Decimal):
        return float(value)
    # UUID (PostgreSQL, etc.)
    if isinstance(value, UUID):
        return str(value)
    # Binary data
    if isinstance(value, (bytes, bytearray, memoryview)):
        if isinstance(value, memoryview):
            value = bytes(value)
        return value.decode("utf-8", errors="replace")
    # Network types (PostgreSQL)
    if isinstance(value, (IPv4Address, IPv6Address, IPv4Network, IPv6Network)):
        return str(value)
    # Enum types
    if isinstance(value, Enum):
        return value.value
    # Path
    if isinstance(value, Path):
        return str(value)
    # Collections
    if isinstance(value, dict):
        return {str(k): _make_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_make_json_safe(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return [_make_json_safe(v) for v in value]
    # Fallback — convert anything else to string
    try:
        return str(value)
    except Exception:
        return repr(value)


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


class AIGenerateQueryRequest(BaseModel):
    """AI query generation request."""
    connection_id: str
    user_query: str


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
       - Validates against configured auth provider

    2. JWT Token (legacy) - For platform-to-sandbox communication
       - Header: Authorization: Bearer <jwt_token>
       - Used for internal platform communication

    Returns:
        Dict with workspace_id, user_id, and other context
    """
    from sandbox.auth.sandbox_auth import get_auth_provider

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
        provider = get_auth_provider()
        if not provider:
            raise AuthenticationError("Auth provider not initialized")

        auth_result = await provider.verify(api_key)
        if not auth_result:
            raise AuthenticationError("Invalid or inactive sandbox API key")

        # Return workspace context
        return {
            "auth_type": "sandbox_api_key",
            "workspace_id": str(auth_result.workspace_id) if auth_result.workspace_id else None,
            "workspace_name": auth_result.workspace_name,
            "user_id": str(auth_result.user_id) if auth_result.user_id else None,
            "api_key_name": auth_result.api_key_name,
            "permissions": auth_result.permissions or {
                "execute_sql": True,
                "execute_python": True,
                "generate_visualizations": True,
            },
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

        # Initialize auth provider if API key auth is enabled
        if config.authentication.enable_api_key_auth:
            from sandbox.auth.sandbox_auth import initialize_auth_provider
            try:
                initialize_auth_provider(config)
                logger.info(f"Auth provider initialized: {config.authentication.provider}")
            except Exception as e:
                logger.error(f"Failed to initialize auth provider: {e}")
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

        # Close auth provider
        if config.authentication.enable_api_key_auth:
            from sandbox.auth.sandbox_auth import get_auth_provider
            provider = get_auth_provider()
            if provider:
                await provider.close()

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
                        "rows": [_make_json_safe(row) for row in result.rows],
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
    # File Upload (CSV, XLSX, XLS)
    # ==========================================================================

    FILE_UPLOAD_DIR = Path("/tmp/sandbox_uploads")
    ALLOWED_FILE_EXTENSIONS = {".csv", ".xlsx", ".xls"}

    @app.post("/api/v1/upload-file", tags=["File Upload"])
    async def upload_file(
        file: UploadFile = File(...),
        name: str = Form(...),
        delimiter: str = Form(","),
        has_header: str = Form("true"),
        selected_sheets: str = Form(""),
        token_data: dict = Depends(verify_sandbox_token),
    ) -> JSONResponse:
        """
        Upload a CSV, XLSX, or XLS file and create connection(s).
        For Excel files with multiple sheets, creates one connection per selected sheet.
        """
        import os
        import pandas as pd
        from sandbox.core.config import (
            DatabaseConnectionConfig, DatabaseType, get_config, save_persisted_connections,
        )
        from pydantic import SecretStr

        if not file.filename:
            raise HTTPException(status_code=400, detail="No file provided")
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in ALLOWED_FILE_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{file_ext}'. Allowed: CSV, XLSX, XLS",
            )

        is_excel = file_ext in (".xlsx", ".xls")

        FILE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        unique_id = str(uuid.uuid4())[:8]
        safe_name = "".join(c for c in name if c.isalnum() or c in "._- ").strip() or "uploaded_data"
        filename = f"{safe_name}_{unique_id}{file_ext}"
        file_path = str(FILE_UPLOAD_DIR / filename)

        try:
            content = await file.read()
            with open(file_path, "wb") as f:
                f.write(content)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

        has_header_bool = has_header.lower() == "true"
        config = get_config()
        now = datetime.now(timezone.utc).isoformat()

        try:
            if is_excel:
                engine = "openpyxl" if file_ext == ".xlsx" else "xlrd"
                excel_file = pd.ExcelFile(file_path, engine=engine)
                all_sheets = excel_file.sheet_names

                if not all_sheets:
                    os.remove(file_path)
                    raise HTTPException(status_code=400, detail="Excel file contains no sheets")

                if selected_sheets.strip():
                    sheets_to_import = [s.strip() for s in selected_sheets.split(",") if s.strip()]
                    invalid = [s for s in sheets_to_import if s not in all_sheets]
                    if invalid:
                        os.remove(file_path)
                        raise HTTPException(
                            status_code=400,
                            detail=f"Sheet(s) not found: {', '.join(invalid)}. Available: {', '.join(all_sheets)}",
                        )
                else:
                    sheets_to_import = all_sheets

                connections = []
                total_rows = 0

                for sheet_name in sheets_to_import:
                    df = pd.read_excel(
                        file_path, sheet_name=sheet_name,
                        header=0 if has_header_bool else None, engine=engine,
                    )
                    row_count = len(df)
                    if row_count == 0:
                        continue

                    total_rows += row_count
                    conn_name = f"{name} - {sheet_name}" if len(sheets_to_import) > 1 else name
                    conn_id = str(uuid.uuid4())

                    # Persist as a config entry with extra_config for file metadata
                    new_conn = DatabaseConnectionConfig(
                        id=conn_id,
                        name=conn_name,
                        db_type=DatabaseType.POSTGRESQL,  # placeholder type
                        host="",
                        port=0,
                        database="",
                        username="",
                        password=SecretStr(""),
                        created_at=now,
                        updated_at=now,
                    )
                    # Store file metadata in extra fields
                    if not hasattr(new_conn, "extra_config"):
                        new_conn.__dict__["extra_config"] = {}
                    new_conn.__dict__["extra_config"] = {
                        "handler_type": "excel",
                        "file_url": file_path,
                        "file_type": file_ext.lstrip("."),
                        "sheet_name": sheet_name,
                        "all_sheets": all_sheets,
                        "header_row": 0 if has_header_bool else None,
                    }

                    config.database_connections.append(new_conn)
                    connections.append({
                        "connection_id": conn_id,
                        "name": conn_name,
                        "sheet_name": sheet_name,
                        "row_count": row_count,
                    })

                if not connections:
                    os.remove(file_path)
                    raise HTTPException(status_code=400, detail="All sheets are empty")

                save_persisted_connections(config)

                return JSONResponse(
                    status_code=201,
                    content={
                        "success": True,
                        "message": f"Excel file uploaded: {len(connections)} sheet(s), {total_rows} total rows",
                        "connection_id": connections[0]["connection_id"],
                        "connections": connections,
                        "row_count": total_rows,
                        "file_path": file_path,
                        "sheets": all_sheets,
                    },
                )
            else:
                # CSV
                df = pd.read_csv(
                    file_path, sep=delimiter,
                    header=0 if has_header_bool else None,
                )
                row_count = len(df)
                column_count = len(df.columns)

                if row_count == 0:
                    os.remove(file_path)
                    raise HTTPException(status_code=400, detail="CSV file is empty")

                conn_id = str(uuid.uuid4())
                new_conn = DatabaseConnectionConfig(
                    id=conn_id,
                    name=name,
                    db_type=DatabaseType.POSTGRESQL,  # placeholder type
                    host="",
                    port=0,
                    database="",
                    username="",
                    password=SecretStr(""),
                    created_at=now,
                    updated_at=now,
                )
                new_conn.__dict__["extra_config"] = {
                    "handler_type": "csv",
                    "file_url": file_path,
                    "file_type": "csv",
                    "delimiter": delimiter,
                    "encoding": "utf-8",
                    "header_row": 0 if has_header_bool else None,
                }

                config.database_connections.append(new_conn)
                save_persisted_connections(config)

                return JSONResponse(
                    status_code=201,
                    content={
                        "success": True,
                        "message": f"CSV uploaded: {row_count} rows, {column_count} columns",
                        "connection_id": conn_id,
                        "row_count": row_count,
                        "column_count": column_count,
                        "file_path": file_path,
                    },
                )

        except HTTPException:
            raise
        except Exception as e:
            import os as _os
            if _os.path.exists(file_path):
                _os.remove(file_path)
            raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)}")

    @app.post("/api/v1/upload-file/sheets", tags=["File Upload"])
    async def get_file_sheets(
        file: UploadFile = File(...),
        token_data: dict = Depends(verify_sandbox_token),
    ) -> JSONResponse:
        """
        Preview sheet names from an uploaded Excel file without creating a connection.
        Used by the frontend to let users select which sheets to import.
        """
        import os
        import pandas as pd

        if not file.filename:
            raise HTTPException(status_code=400, detail="No file provided")
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in (".xlsx", ".xls"):
            raise HTTPException(status_code=400, detail="Sheet detection is only for Excel files")

        FILE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        temp_path = str(FILE_UPLOAD_DIR / f"_temp_{uuid.uuid4().hex[:8]}{file_ext}")

        try:
            content = await file.read()
            with open(temp_path, "wb") as f:
                f.write(content)

            engine = "openpyxl" if file_ext == ".xlsx" else "xlrd"
            excel_file = pd.ExcelFile(temp_path, engine=engine)
            sheets = []
            for sheet_name in excel_file.sheet_names:
                df = pd.read_excel(temp_path, sheet_name=sheet_name, nrows=5, engine=engine)
                sheets.append({
                    "name": sheet_name,
                    "columns": [str(c) for c in df.columns],
                    "preview_rows": len(df),
                })

            return JSONResponse(content={"sheets": sheets})
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to read Excel file: {str(e)}")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    # ==========================================================================
    # Schema Sync
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
        Returns database schema metadata with tables, columns, and optional sample data.
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

        Pulls all connection metadata in one call.
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
    # SQL Pad Integration
    # ==========================================================================

    @app.post("/api/v1/sqlpad/connection", tags=["SQL Pad"])
    async def create_sqlpad_connection(
        connection_id: str,
        token_data: dict = Depends(verify_sandbox_token),
    ) -> JSONResponse:
        """
        Create or update SQL Pad connection for a database.

        This syncs the sandbox database connection to SQL Pad so users can
        explore and query their data using SQL Pad's UI.
        """
        from sandbox.services.sqlpad_service import get_sqlpad_service
        from sandbox.core.config import get_config

        config = get_config()

        # Find connection in config
        conn_config = next(
            (c for c in config.database_connections if c.id == connection_id),
            None
        )

        if not conn_config:
            raise HTTPException(
                status_code=404,
                detail=f"Connection {connection_id} not found"
            )

        try:
            sqlpad = get_sqlpad_service()

            result = await sqlpad.create_or_update_connection(
                connection_id=conn_config.id,
                name=conn_config.name,
                db_type=conn_config.db_type.value,
                host=conn_config.host,
                port=conn_config.port,
                database=conn_config.database,
                username=conn_config.username,
                password=conn_config.password.get_secret_value(),
                schema=conn_config.schema_name,
            )

            return JSONResponse(content={
                "status": "success",
                "data": {
                    "connection_id": result.get("id"),
                    "name": result.get("name"),
                    "driver": result.get("driver"),
                }
            })

        except Exception as e:
            logger.error("sqlpad_connection_error", error=str(e))
            raise HTTPException(status_code=500, detail=str(e))

    @app.delete("/api/v1/sqlpad/connection/{connection_id}", tags=["SQL Pad"])
    async def delete_sqlpad_connection(
        connection_id: str,
        token_data: dict = Depends(verify_sandbox_token),
    ) -> JSONResponse:
        """Delete a SQL Pad connection."""
        from sandbox.services.sqlpad_service import get_sqlpad_service

        try:
            sqlpad = get_sqlpad_service()
            await sqlpad.delete_connection(connection_id)

            return JSONResponse(content={
                "status": "success",
                "message": "Connection deleted"
            })

        except Exception as e:
            logger.error("sqlpad_delete_error", error=str(e))
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/v1/sqlpad/connections", tags=["SQL Pad"])
    async def list_sqlpad_connections(
        token_data: dict = Depends(verify_sandbox_token),
    ) -> JSONResponse:
        """List all SQL Pad connections."""
        from sandbox.services.sqlpad_service import get_sqlpad_service

        try:
            sqlpad = get_sqlpad_service()
            connections = await sqlpad.list_connections()

            return JSONResponse(content={
                "status": "success",
                "data": connections
            })

        except Exception as e:
            logger.error("sqlpad_list_error", error=str(e))
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/v1/sqlpad/embed-url", tags=["SQL Pad"])
    async def get_sqlpad_embed_url(
        connection_id: str | None = None,
        token_data: dict = Depends(verify_sandbox_token),
    ) -> JSONResponse:
        """
        Get SQL Pad embed URL with authentication token.

        Use this URL in an iframe to embed SQL Pad in your UI.
        """
        from sandbox.services.sqlpad_service import get_sqlpad_service

        try:
            sqlpad = get_sqlpad_service()
            embed_url = await sqlpad.get_embed_url(connection_id)

            return JSONResponse(content={
                "status": "success",
                "data": {
                    "embed_url": embed_url,
                    "connection_id": connection_id,
                }
            })

        except Exception as e:
            logger.error("sqlpad_embed_url_error", error=str(e))
            raise HTTPException(status_code=500, detail=str(e))

    # ==========================================================================
    # AI Query Generation (proxies to MVP backend)
    # ==========================================================================

    async def _extract_api_key(
        x_api_key: str | None = Header(None, alias="X-API-Key"),
        authorization: str | None = Header(None),
    ) -> str | None:
        """Extract the raw API key from request headers."""
        if x_api_key:
            return x_api_key
        if authorization and authorization.startswith("Bearer "):
            return authorization[7:]
        return None

    @app.post("/api/v1/ai/generate-query", tags=["AI"])
    async def ai_generate_query(
        request: AIGenerateQueryRequest,
        token_data: dict = Depends(verify_sandbox_token),
        api_key: str | None = Depends(_extract_api_key),
    ) -> JSONResponse:
        """
        Generate SQL query from natural language using AI.

        Proxies the request to the MVP backend which runs the LangGraph agent.
        The sandbox just forwards connection_id + user_query.
        """
        import httpx

        config = get_config()

        # Derive MVP base URL from remote auth URL
        # e.g. "http://host.docker.internal:18000/api/v1/sandbox/validate-key"
        # -> "http://host.docker.internal:18000"
        remote_url = getattr(config.authentication, "remote_url", "")
        if "/api/" in remote_url:
            mvp_base_url = remote_url.split("/api/")[0]
        else:
            mvp_base_url = remote_url.rstrip("/")

        if not mvp_base_url:
            raise HTTPException(
                status_code=503,
                detail="AI query generation not available (MVP URL not configured)",
            )

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{mvp_base_url}/api/v1/generate-sql",
                    json={
                        "connection_id": request.connection_id,
                        "user_query": request.user_query,
                    },
                    headers=headers,
                )

            try:
                content = response.json()
            except Exception:
                content = {"success": False, "error": f"MVP returned HTTP {response.status_code}: {response.text[:200]}"}

            return JSONResponse(
                status_code=response.status_code if response.status_code < 500 else 502,
                content=content,
            )

        except httpx.TimeoutException:
            raise HTTPException(
                status_code=504,
                detail="AI query generation timed out",
            )
        except Exception as e:
            logger.error("ai_generate_query_error", error=str(e))
            raise HTTPException(status_code=502, detail=str(e))

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
