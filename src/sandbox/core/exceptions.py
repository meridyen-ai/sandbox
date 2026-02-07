"""
Sandbox Exception Hierarchy

All custom exceptions for the sandbox execution engine.
Follows best practices for exception handling with proper inheritance
and context preservation.
"""

from typing import Any


class SandboxError(Exception):
    """Base exception for all sandbox errors."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.details = details or {}
        self.cause = cause

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for API responses."""
        return {
            "error": self.error_code,
            "message": self.message,
            "details": self.details,
        }

    def __str__(self) -> str:
        if self.cause:
            return f"{self.message} (caused by: {self.cause})"
        return self.message


class ExecutionError(SandboxError):
    """Error during code execution (SQL or Python)."""

    def __init__(
        self,
        message: str,
        *,
        execution_type: str = "unknown",
        query: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.execution_type = execution_type
        self.query = query
        self.details["execution_type"] = execution_type
        if query:
            # Truncate query for safety
            self.details["query_preview"] = query[:200] + "..." if len(query) > 200 else query


class SQLExecutionError(ExecutionError):
    """Error during SQL execution."""

    def __init__(self, message: str, *, query: str | None = None, **kwargs: Any) -> None:
        super().__init__(message, execution_type="sql", query=query, **kwargs)


class PythonExecutionError(ExecutionError):
    """Error during Python execution."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        line_number: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, execution_type="python", **kwargs)
        self.code = code
        self.line_number = line_number
        if line_number:
            self.details["line_number"] = line_number


class SecurityError(SandboxError):
    """Security violation detected."""

    def __init__(
        self,
        message: str,
        *,
        violation_type: str = "unknown",
        blocked_content: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.violation_type = violation_type
        self.details["violation_type"] = violation_type
        # Never include blocked content in details for security
        self._blocked_content = blocked_content


class BannedOperationError(SecurityError):
    """Attempted to use banned operation or import."""

    def __init__(self, message: str, *, operation: str, **kwargs: Any) -> None:
        super().__init__(message, violation_type="banned_operation", **kwargs)
        self.operation = operation
        self.details["operation"] = operation


class DataExfiltrationError(SecurityError):
    """Attempted data exfiltration detected."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, violation_type="data_exfiltration", **kwargs)


class ConnectionError(SandboxError):
    """Database connection error."""

    def __init__(
        self,
        message: str,
        *,
        connection_id: str | None = None,
        db_type: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.connection_id = connection_id
        self.db_type = db_type
        if connection_id:
            self.details["connection_id"] = connection_id
        if db_type:
            self.details["db_type"] = db_type


class TimeoutError(SandboxError):
    """Execution timeout exceeded."""

    def __init__(
        self,
        message: str,
        *,
        timeout_seconds: float,
        execution_type: str = "unknown",
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.timeout_seconds = timeout_seconds
        self.execution_type = execution_type
        self.details["timeout_seconds"] = timeout_seconds
        self.details["execution_type"] = execution_type


class ResourceLimitError(SandboxError):
    """Resource limit exceeded (memory, CPU, output size)."""

    def __init__(
        self,
        message: str,
        *,
        resource_type: str,
        limit: int | float,
        actual: int | float | None = None,
        unit: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.resource_type = resource_type
        self.limit = limit
        self.actual = actual
        self.unit = unit
        self.details["resource_type"] = resource_type
        self.details["limit"] = f"{limit}{unit}"
        if actual is not None:
            self.details["actual"] = f"{actual}{unit}"


class MemoryLimitError(ResourceLimitError):
    """Memory limit exceeded."""

    def __init__(self, limit_mb: int, actual_mb: int | None = None, **kwargs: Any) -> None:
        super().__init__(
            f"Memory limit exceeded: {actual_mb}MB > {limit_mb}MB" if actual_mb else f"Memory limit of {limit_mb}MB exceeded",
            resource_type="memory",
            limit=limit_mb,
            actual=actual_mb,
            unit="MB",
            **kwargs,
        )


class OutputSizeLimitError(ResourceLimitError):
    """Output size limit exceeded."""

    def __init__(self, limit_kb: int, actual_kb: int | None = None, **kwargs: Any) -> None:
        super().__init__(
            f"Output size limit exceeded: {actual_kb}KB > {limit_kb}KB" if actual_kb else f"Output size limit of {limit_kb}KB exceeded",
            resource_type="output_size",
            limit=limit_kb,
            actual=actual_kb,
            unit="KB",
            **kwargs,
        )


class RowLimitError(ResourceLimitError):
    """Row limit exceeded."""

    def __init__(self, limit: int, actual: int | None = None, **kwargs: Any) -> None:
        super().__init__(
            f"Row limit exceeded: {actual} > {limit}" if actual else f"Row limit of {limit} exceeded",
            resource_type="rows",
            limit=limit,
            actual=actual,
            **kwargs,
        )


class ConfigurationError(SandboxError):
    """Configuration error."""

    def __init__(self, message: str, *, config_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        if config_key:
            self.details["config_key"] = config_key


class AuthenticationError(SandboxError):
    """Authentication failed."""

    def __init__(self, message: str = "Authentication failed", **kwargs: Any) -> None:
        super().__init__(message, error_code="AUTHENTICATION_ERROR", **kwargs)


class AuthorizationError(SandboxError):
    """Authorization failed - insufficient permissions."""

    def __init__(
        self,
        message: str = "Insufficient permissions",
        *,
        required_permission: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, error_code="AUTHORIZATION_ERROR", **kwargs)
        if required_permission:
            self.details["required_permission"] = required_permission


class ValidationError(SandboxError):
    """Input validation error."""

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        value: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, error_code="VALIDATION_ERROR", **kwargs)
        if field:
            self.details["field"] = field
        # Never include actual value in details for security
