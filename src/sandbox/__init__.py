"""
Meridyen.ai Sandbox Execution Engine

A secure, isolated execution environment for SQL and Python code execution.
"""

__version__ = "1.0.0"
__author__ = "Meridyen.ai"

from sandbox.core.config import SandboxConfig, get_config
from sandbox.core.exceptions import (
    SandboxError,
    ExecutionError,
    SecurityError,
    ConnectionError,
    TimeoutError,
    ResourceLimitError,
)

__all__ = [
    "__version__",
    "SandboxConfig",
    "get_config",
    "SandboxError",
    "ExecutionError",
    "SecurityError",
    "ConnectionError",
    "TimeoutError",
    "ResourceLimitError",
]
