"""
Base classes for execution engines.

Defines common interfaces and data structures used by all executors.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, TypeVar

from sandbox.core.config import ResourceLimitsConfig
from sandbox.core.logging import get_logger

logger = get_logger(__name__)


class ExecutionStatus(str, Enum):
    """Status of an execution."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    RESOURCE_LIMIT = "resource_limit"


@dataclass
class ExecutionContext:
    """
    Context for an execution request.

    Contains all information needed to execute a request,
    including security context, resource limits, and tracing info.
    """
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    workspace_id: str | None = None
    connection_id: str | None = None
    user_id: str | None = None

    # Resource limits (override defaults from config)
    max_rows: int | None = None
    timeout_seconds: int | None = None
    max_memory_mb: int | None = None
    max_output_size_kb: int | None = None

    # Execution options
    include_metadata: bool = True
    streaming: bool = False

    # Tracing
    trace_id: str | None = None
    span_id: str | None = None

    def __post_init__(self) -> None:
        if self.trace_id is None:
            self.trace_id = self.request_id

    def get_timeout(self, config: ResourceLimitsConfig, default: int = 60) -> int:
        """Get timeout, preferring context value over config."""
        if self.timeout_seconds is not None:
            return self.timeout_seconds
        return config.query_timeout_seconds or default

    def get_max_rows(self, config: ResourceLimitsConfig) -> int:
        """Get max rows, preferring context value over config."""
        if self.max_rows is not None:
            return self.max_rows
        return config.max_rows


@dataclass
class ExecutionMetrics:
    """Metrics captured during execution."""
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    duration_ms: float = 0.0
    rows_processed: int = 0
    rows_returned: int = 0
    memory_used_mb: float = 0.0
    cpu_time_seconds: float = 0.0

    def complete(self) -> None:
        """Mark execution as complete and calculate duration."""
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "duration_ms": round(self.duration_ms, 2),
            "rows_processed": self.rows_processed,
            "rows_returned": self.rows_returned,
            "memory_used_mb": round(self.memory_used_mb, 2),
            "cpu_time_seconds": round(self.cpu_time_seconds, 3),
        }


@dataclass
class ExecutionResult:
    """Base result class for all execution types."""
    request_id: str
    status: ExecutionStatus
    metrics: ExecutionMetrics = field(default_factory=ExecutionMetrics)
    error_message: str | None = None
    error_code: str | None = None

    def is_success(self) -> bool:
        """Check if execution was successful."""
        return self.status == ExecutionStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "request_id": self.request_id,
            "status": self.status.value,
            "metrics": self.metrics.to_dict(),
        }
        if self.error_message:
            result["error"] = {
                "message": self.error_message,
                "code": self.error_code,
            }
        return result


T = TypeVar("T", bound=ExecutionResult)


class BaseExecutor(ABC, Generic[T]):
    """
    Abstract base class for all executors.

    Provides common functionality like timeout handling,
    resource tracking, and logging.
    """

    def __init__(self, config: ResourceLimitsConfig | None = None) -> None:
        from sandbox.core.config import get_config
        self.config = config or get_config().resource_limits
        self._logger = get_logger(self.__class__.__name__)

    @abstractmethod
    async def execute(self, context: ExecutionContext, **kwargs: Any) -> T:
        """
        Execute the operation.

        Args:
            context: Execution context
            **kwargs: Executor-specific arguments

        Returns:
            Execution result
        """
        pass

    @abstractmethod
    async def validate(self, context: ExecutionContext, **kwargs: Any) -> list[str]:
        """
        Validate the execution request.

        Args:
            context: Execution context
            **kwargs: Executor-specific arguments

        Returns:
            List of validation error messages (empty if valid)
        """
        pass

    async def execute_with_validation(self, context: ExecutionContext, **kwargs: Any) -> T:
        """
        Validate and execute.

        Convenience method that validates first, then executes.
        """
        errors = await self.validate(context, **kwargs)
        if errors:
            from sandbox.core.exceptions import ValidationError
            raise ValidationError(
                f"Validation failed: {'; '.join(errors)}",
                details={"errors": errors},
            )
        return await self.execute(context, **kwargs)

    def _log_start(self, context: ExecutionContext, execution_type: str, **extra: Any) -> None:
        """Log execution start."""
        self._logger.info(
            "execution_started",
            request_id=context.request_id,
            execution_type=execution_type,
            workspace_id=context.workspace_id,
            **extra,
        )

    def _log_complete(
        self,
        context: ExecutionContext,
        result: ExecutionResult,
        execution_type: str,
        **extra: Any,
    ) -> None:
        """Log execution completion."""
        log_method = self._logger.info if result.is_success() else self._logger.warning
        log_method(
            "execution_completed",
            request_id=context.request_id,
            execution_type=execution_type,
            status=result.status.value,
            duration_ms=result.metrics.duration_ms,
            **extra,
        )

    def _log_error(
        self,
        context: ExecutionContext,
        error: Exception,
        execution_type: str,
        **extra: Any,
    ) -> None:
        """Log execution error."""
        self._logger.error(
            "execution_error",
            request_id=context.request_id,
            execution_type=execution_type,
            error_type=type(error).__name__,
            error_message=str(error),
            **extra,
        )
