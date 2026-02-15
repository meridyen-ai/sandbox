"""
Authentication Provider Interface.

Defines the contract that all authentication backends must implement.
Custom providers can subclass AuthProvider and implement the verify() method.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AuthResult:
    """Result of a successful authentication attempt."""

    authenticated: bool
    workspace_id: str | None = None
    workspace_name: str | None = None
    user_id: str | None = None
    api_key_name: str | None = None
    permissions: dict[str, Any] = field(
        default_factory=lambda: {
            "execute_sql": True,
            "execute_python": True,
            "generate_visualizations": True,
        }
    )
    metadata: dict[str, Any] = field(default_factory=dict)


class AuthProvider(ABC):
    """
    Abstract base class for authentication providers.

    Built-in providers:
    - StaticKeyAuthProvider: validates against a configured list of API keys
    - RemoteAuthProvider: validates by calling an external HTTP endpoint
    - NoopAuthProvider: accepts all requests (development only)

    To create a custom provider, subclass this and implement verify().
    """

    @abstractmethod
    async def verify(self, api_key: str) -> AuthResult | None:
        """
        Verify an API key or token.

        Args:
            api_key: The API key or token to verify.

        Returns:
            AuthResult if valid, None if invalid.
        """
        ...

    async def close(self) -> None:
        """Clean up resources. Override if your provider holds connections."""

    async def health_check(self) -> bool:
        """Check if the auth provider is healthy. Override for remote providers."""
        return True
