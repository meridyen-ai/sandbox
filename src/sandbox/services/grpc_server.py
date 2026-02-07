"""
gRPC Server Implementation

Implements the SandboxExecutionService for secure code execution.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from concurrent import futures
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import grpc
from google.protobuf import struct_pb2, timestamp_pb2
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from grpc_reflection.v1alpha import reflection

from sandbox.core.config import get_config
from sandbox.core.exceptions import SandboxError, ValidationError
from sandbox.core.logging import get_logger, bind_context, clear_context
from sandbox.execution.base import ExecutionContext, ExecutionStatus
from sandbox.execution.sql_executor import SQLExecutor
from sandbox.execution.python_executor import PythonExecutor
from sandbox.visualization.generator import VisualizationGenerator, ChartType

logger = get_logger(__name__)

# Note: In production, these would be generated from the .proto file
# For this implementation, we'll define the message classes inline
# Run: python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. sandbox.proto


class SandboxExecutionServicer:
    """
    gRPC servicer for sandbox execution.

    Implements:
    - ExecuteSQL: Execute SQL queries
    - ExecutePython: Execute Python code
    - CreateVisualization: Generate visualizations
    - HealthCheck: Health status
    - GetCapabilities: Sandbox capabilities
    """

    def __init__(self) -> None:
        self.config = get_config()
        self.sql_executor = SQLExecutor()
        self.python_executor = PythonExecutor()
        self.viz_generator = VisualizationGenerator()
        self._start_time = datetime.now(timezone.utc)
        self._logger = get_logger("grpc_servicer")

    async def ExecuteSQL(
        self,
        request: Any,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[Any]:
        """Execute SQL query and stream results."""
        request_id = request.context.request_id or str(uuid.uuid4())
        bind_context(request_id=request_id)

        self._logger.info(
            "execute_sql_started",
            request_id=request_id,
            workspace_id=request.context.workspace_id,
        )

        try:
            # Build execution context
            exec_context = self._build_execution_context(request.context)

            # Validate request
            errors = await self.sql_executor.validate(exec_context, query=request.query)
            if errors:
                yield self._build_error_response(
                    request_id,
                    "VALIDATION_ERROR",
                    "; ".join(errors),
                )
                return

            # Execute query
            result = await self.sql_executor.execute(
                exec_context,
                query=request.query,
                parameters=self._struct_to_dict(request.parameters) if request.parameters else None,
            )

            # Build response
            yield self._build_sql_response(request_id, result)

        except SandboxError as e:
            self._logger.warning(
                "execute_sql_failed",
                request_id=request_id,
                error=str(e),
            )
            yield self._build_error_response(request_id, e.error_code, e.message)

        except Exception as e:
            self._logger.error(
                "execute_sql_error",
                request_id=request_id,
                error=str(e),
                exc_info=True,
            )
            yield self._build_error_response(request_id, "INTERNAL_ERROR", str(e))

        finally:
            clear_context()

    async def ExecutePython(
        self,
        request: Any,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[Any]:
        """Execute Python code and stream results."""
        request_id = request.context.request_id or str(uuid.uuid4())
        bind_context(request_id=request_id)

        self._logger.info(
            "execute_python_started",
            request_id=request_id,
            workspace_id=request.context.workspace_id,
        )

        try:
            # Build execution context
            exec_context = self._build_execution_context(request.context)

            # Validate request
            errors = await self.python_executor.validate(exec_context, code=request.code)
            if errors:
                yield self._build_error_response(
                    request_id,
                    "VALIDATION_ERROR",
                    "; ".join(errors),
                )
                return

            # Build input data
            input_data = {}
            if request.input_data:
                input_data["data"] = self._struct_to_dict(request.input_data)
            if request.variables:
                input_data["variables"] = {
                    k: self._value_to_python(v) for k, v in request.variables.items()
                }

            # Execute code
            result = await self.python_executor.execute(
                exec_context,
                code=request.code,
                input_data=input_data,
            )

            # Build response
            yield self._build_python_response(request_id, result)

        except SandboxError as e:
            self._logger.warning(
                "execute_python_failed",
                request_id=request_id,
                error=str(e),
            )
            yield self._build_error_response(request_id, e.error_code, e.message)

        except Exception as e:
            self._logger.error(
                "execute_python_error",
                request_id=request_id,
                error=str(e),
                exc_info=True,
            )
            yield self._build_error_response(request_id, "INTERNAL_ERROR", str(e))

        finally:
            clear_context()

    async def CreateVisualization(
        self,
        request: Any,
        context: grpc.aio.ServicerContext,
    ) -> Any:
        """Create visualization from data."""
        request_id = request.context.request_id or str(uuid.uuid4())
        bind_context(request_id=request_id)

        self._logger.info(
            "create_visualization_started",
            request_id=request_id,
        )

        try:
            exec_context = self._build_execution_context(request.context)

            # Get data
            data = self._struct_to_dict(request.data) if request.data else []

            # Determine chart type
            chart_type = ChartType.AUTO
            if request.chart_type:
                chart_type_map = {
                    1: ChartType.AUTO,
                    2: ChartType.LINE,
                    3: ChartType.BAR,
                    4: ChartType.PIE,
                    5: ChartType.SCATTER,
                    6: ChartType.HEATMAP,
                    7: ChartType.TABLE,
                }
                chart_type = chart_type_map.get(request.chart_type, ChartType.AUTO)

            # Generate visualization
            result = await self.viz_generator.generate(
                exec_context,
                data=data if isinstance(data, list) else [data],
                instruction=request.instruction,
                chart_type=chart_type,
            )

            return self._build_visualization_response(request_id, result)

        except Exception as e:
            self._logger.error(
                "create_visualization_error",
                request_id=request_id,
                error=str(e),
            )
            return self._build_visualization_error_response(request_id, str(e))

        finally:
            clear_context()

    async def HealthCheck(
        self,
        request: Any,
        context: grpc.aio.ServicerContext,
    ) -> Any:
        """Return health status."""
        # Build health response
        response = {
            "status": 1,  # HEALTHY
            "version": "1.0.0",
            "uptime_since": self._start_time.isoformat(),
        }

        if request.include_details:
            response["components"] = {
                "sql_executor": {"status": 1, "message": "OK"},
                "python_executor": {"status": 1, "message": "OK"},
                "visualization": {"status": 1, "message": "OK"},
            }

        return response

    async def GetCapabilities(
        self,
        request: Any,
        context: grpc.aio.ServicerContext,
    ) -> Any:
        """Return sandbox capabilities."""
        from sandbox.connectors.factory import get_available_connectors

        return {
            "sandbox_id": self.config.platform.sandbox_id,
            "version": "1.0.0",
            "supported_databases": get_available_connectors(),
            "supported_packages": list(self.config.security.allowed_python_imports),
            "resource_limits": {
                "max_memory_mb": self.config.resource_limits.max_memory_mb,
                "max_cpu_seconds": self.config.resource_limits.max_cpu_seconds,
                "max_output_size_kb": self.config.resource_limits.max_output_size_kb,
                "max_rows": self.config.resource_limits.max_rows,
                "max_concurrent_queries": self.config.resource_limits.max_concurrent_queries,
                "query_timeout_seconds": self.config.resource_limits.query_timeout_seconds,
                "python_timeout_seconds": self.config.resource_limits.python_timeout_seconds,
            },
            "supports_streaming": True,
            "supports_visualization": True,
            "has_local_llm": self.config.local_llm.enabled,
            "local_llm_model": self.config.local_llm.model_name if self.config.local_llm.enabled else None,
        }

    # Helper methods

    def _build_execution_context(self, proto_context: Any) -> ExecutionContext:
        """Build ExecutionContext from protobuf context."""
        return ExecutionContext(
            request_id=proto_context.request_id or str(uuid.uuid4()),
            workspace_id=proto_context.workspace_id or None,
            connection_id=proto_context.connection_id or None,
            user_id=proto_context.user_id or None,
            max_rows=proto_context.max_rows if proto_context.HasField("max_rows") else None,
            timeout_seconds=proto_context.timeout_seconds if proto_context.HasField("timeout_seconds") else None,
            max_memory_mb=proto_context.max_memory_mb if proto_context.HasField("max_memory_mb") else None,
            max_output_size_kb=proto_context.max_output_size_kb if proto_context.HasField("max_output_size_kb") else None,
            trace_id=proto_context.trace_id or None,
            span_id=proto_context.span_id or None,
        )

    def _struct_to_dict(self, struct: struct_pb2.Struct) -> dict[str, Any]:
        """Convert protobuf Struct to Python dict."""
        from google.protobuf.json_format import MessageToDict
        return MessageToDict(struct)

    def _value_to_python(self, value: Any) -> Any:
        """Convert protobuf Value to Python value."""
        from google.protobuf.json_format import MessageToDict
        return MessageToDict(value)

    def _build_error_response(
        self, request_id: str, error_code: str, message: str
    ) -> dict[str, Any]:
        """Build error response."""
        return {
            "request_id": request_id,
            "status": 4,  # ERROR
            "error": {
                "code": error_code,
                "message": message,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _build_sql_response(self, request_id: str, result: Any) -> dict[str, Any]:
        """Build SQL execution response."""
        return {
            "request_id": request_id,
            "status": 3 if result.is_success() else 4,  # SUCCESS or ERROR
            "sql_result": {
                "columns": [
                    {"name": c.name, "data_type": c.data_type, "is_masked": c.is_masked}
                    for c in result.columns
                ],
                "rows": result.rows,
                "row_count": result.row_count,
                "total_rows_available": result.total_rows_available,
            },
            "metrics": result.metrics.to_dict(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _build_python_response(self, request_id: str, result: Any) -> dict[str, Any]:
        """Build Python execution response."""
        return {
            "request_id": request_id,
            "status": 3 if result.is_success() else 4,
            "python_result": {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "result_data": result.result_data,
                "variables": result.variables,
            },
            "metrics": result.metrics.to_dict(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _build_visualization_response(self, request_id: str, result: Any) -> dict[str, Any]:
        """Build visualization response."""
        return {
            "request_id": request_id,
            "status": 3 if result.status == ExecutionStatus.SUCCESS else 4,
            "plotly_spec": result.plotly_spec,
            "insight": result.insight,
            "explanation": result.explanation,
            "metrics": result.metrics.to_dict(),
        }

    def _build_visualization_error_response(self, request_id: str, message: str) -> dict[str, Any]:
        """Build visualization error response."""
        return {
            "request_id": request_id,
            "status": 4,
            "error": {
                "code": "VISUALIZATION_ERROR",
                "message": message,
            },
        }


class SandboxGRPCServer:
    """
    gRPC server for the sandbox.

    Features:
    - TLS/mTLS support
    - Health checking
    - Reflection for debugging
    - Graceful shutdown
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 50051) -> None:
        self.host = host
        self.port = port
        self.config = get_config()
        self._server: grpc.aio.Server | None = None
        self._servicer = SandboxExecutionServicer()
        self._logger = get_logger("grpc_server")

    async def start(self) -> None:
        """Start the gRPC server."""
        self._server = grpc.aio.server(
            futures.ThreadPoolExecutor(max_workers=self.config.server.workers),
            options=[
                ("grpc.max_send_message_length", 50 * 1024 * 1024),  # 50MB
                ("grpc.max_receive_message_length", 50 * 1024 * 1024),
                ("grpc.keepalive_time_ms", 30000),
                ("grpc.keepalive_timeout_ms", 10000),
            ],
        )

        # Add services
        # Note: In production, use generated servicer classes
        # add_SandboxExecutionServiceServicer_to_server(self._servicer, self._server)

        # Add health checking
        health_servicer = health.HealthServicer()
        health_pb2_grpc.add_HealthServicer_to_server(health_servicer, self._server)
        health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
        health_servicer.set(
            "meridyen.sandbox.v1.SandboxExecutionService",
            health_pb2.HealthCheckResponse.SERVING,
        )

        # Add reflection for debugging (disable in production)
        if self.config.debug:
            SERVICE_NAMES = (
                "meridyen.sandbox.v1.SandboxExecutionService",
                reflection.SERVICE_NAME,
            )
            reflection.enable_server_reflection(SERVICE_NAMES, self._server)

        # Configure TLS if enabled
        if self.config.platform.mtls_enabled:
            credentials = self._load_server_credentials()
            self._server.add_secure_port(f"{self.host}:{self.port}", credentials)
        else:
            self._server.add_insecure_port(f"{self.host}:{self.port}")

        await self._server.start()
        self._logger.info(
            "grpc_server_started",
            host=self.host,
            port=self.port,
            tls_enabled=self.config.platform.mtls_enabled,
        )

    async def stop(self, grace_period: float = 5.0) -> None:
        """Stop the gRPC server gracefully."""
        if self._server:
            self._logger.info("grpc_server_stopping", grace_period=grace_period)
            await self._server.stop(grace_period)
            self._logger.info("grpc_server_stopped")

    async def wait_for_termination(self) -> None:
        """Wait for server termination."""
        if self._server:
            await self._server.wait_for_termination()

    def _load_server_credentials(self) -> grpc.ServerCredentials:
        """Load TLS credentials for the server."""
        platform = self.config.platform

        if not platform.client_cert_path or not platform.client_key_path:
            raise ValueError("TLS enabled but certificate paths not configured")

        with open(platform.client_cert_path, "rb") as f:
            server_cert = f.read()
        with open(platform.client_key_path, "rb") as f:
            server_key = f.read()

        ca_cert = None
        if platform.ca_cert_path:
            with open(platform.ca_cert_path, "rb") as f:
                ca_cert = f.read()

        return grpc.ssl_server_credentials(
            [(server_key, server_cert)],
            root_certificates=ca_cert,
            require_client_auth=ca_cert is not None,
        )
