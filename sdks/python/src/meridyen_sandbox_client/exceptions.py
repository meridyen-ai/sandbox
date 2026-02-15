"""Sandbox client exceptions."""

from __future__ import annotations

from typing import Any


class SandboxError(Exception):
    """Base exception for sandbox client errors."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.details = details


class SandboxAuthError(SandboxError):
    """Authentication failed (401)."""

    def __init__(self, message: str = "Authentication failed") -> None:
        super().__init__(message, status_code=401)


class SandboxTimeoutError(SandboxError):
    """Request timed out."""

    def __init__(self, message: str = "Request timed out") -> None:
        super().__init__(message, status_code=408)


class SandboxConnectionError(SandboxError):
    """Could not connect to sandbox."""

    def __init__(self, message: str = "Could not connect to sandbox") -> None:
        super().__init__(message)
