"""
Structured Logging Configuration

Uses structlog for structured, JSON-formatted logging suitable for
production environments and log aggregation systems.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import Processor

from sandbox.core.config import get_config, LogLevel


def _add_sandbox_context(
    logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Add sandbox-specific context to log entries."""
    config = get_config()
    event_dict["sandbox_id"] = config.platform.sandbox_id
    event_dict["workspace_id"] = config.platform.workspace_id
    event_dict["execution_mode"] = config.execution_mode.value
    event_dict["environment"] = config.environment
    return event_dict


def _filter_sensitive_data(
    logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Filter sensitive data from log entries."""
    sensitive_keys = {
        "password", "secret", "token", "key", "credential", "auth",
        "ssn", "credit_card", "api_key", "private_key",
    }

    def _mask_value(key: str, value: Any) -> Any:
        key_lower = key.lower()
        for sensitive in sensitive_keys:
            if sensitive in key_lower:
                if isinstance(value, str):
                    return "***MASKED***"
                return "***MASKED***"
        return value

    def _filter_dict(d: dict[str, Any]) -> dict[str, Any]:
        return {k: _mask_value(k, v) for k, v in d.items()}

    return _filter_dict(event_dict)


def _truncate_large_values(
    logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Truncate large values to prevent log bloat."""
    max_length = 1000

    def _truncate(value: Any) -> Any:
        if isinstance(value, str) and len(value) > max_length:
            return value[:max_length] + f"... [truncated, total length: {len(value)}]"
        if isinstance(value, (list, tuple)) and len(value) > 50:
            return list(value[:50]) + [f"... [{len(value) - 50} more items]"]
        return value

    return {k: _truncate(v) for k, v in event_dict.items()}


def setup_logging(
    log_level: LogLevel | str | None = None,
    json_format: bool | None = None,
) -> None:
    """
    Configure structured logging for the sandbox.

    Args:
        log_level: Log level (defaults to config value)
        json_format: Use JSON format (defaults to True in production)
    """
    config = get_config()

    if log_level is None:
        log_level = config.log_level
    if isinstance(log_level, str):
        log_level = LogLevel(log_level.upper())

    if json_format is None:
        json_format = config.is_production()

    # Convert LogLevel enum to logging level
    level = getattr(logging, log_level.value)

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    # Build processor chain
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        _add_sandbox_context,
        _filter_sensitive_data,
        _truncate_large_values,
    ]

    if json_format:
        # Production: JSON format for log aggregation
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Development: Human-readable format
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)


def bind_context(**kwargs: Any) -> None:
    """
    Bind context variables to all subsequent log entries.

    Useful for adding request-specific context like request_id.
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def unbind_context(*keys: str) -> None:
    """Remove context variables."""
    structlog.contextvars.unbind_contextvars(*keys)


def clear_context() -> None:
    """Clear all context variables."""
    structlog.contextvars.clear_contextvars()


# Convenience functions for common log operations
def log_execution_start(
    execution_type: str,
    request_id: str,
    **extra: Any,
) -> None:
    """Log execution start."""
    logger = get_logger("execution")
    logger.info(
        "execution_started",
        execution_type=execution_type,
        request_id=request_id,
        **extra,
    )


def log_execution_complete(
    execution_type: str,
    request_id: str,
    duration_ms: float,
    success: bool,
    **extra: Any,
) -> None:
    """Log execution completion."""
    logger = get_logger("execution")
    log_method = logger.info if success else logger.warning
    log_method(
        "execution_completed",
        execution_type=execution_type,
        request_id=request_id,
        duration_ms=duration_ms,
        success=success,
        **extra,
    )


def log_security_event(
    event_type: str,
    request_id: str | None = None,
    **extra: Any,
) -> None:
    """Log security-related event."""
    logger = get_logger("security")
    logger.warning(
        "security_event",
        event_type=event_type,
        request_id=request_id,
        **extra,
    )
