"""
Authentication Provider Factory.

Initializes the appropriate auth provider based on configuration.
"""

from __future__ import annotations

import logging
from typing import Optional

from sandbox.auth.base import AuthProvider
from sandbox.auth.providers import (
    NoopAuthProvider,
    RemoteAuthProvider,
    StaticKeyAuthProvider,
)

logger = logging.getLogger(__name__)

_provider: Optional[AuthProvider] = None


def initialize_auth_provider(config) -> AuthProvider:
    """
    Initialize the global auth provider based on config.

    Reads config.authentication.provider to determine which backend to use:
    - "static": validates against keys in config.authentication.static_keys
    - "remote": validates via HTTP POST to config.authentication.remote_url
    - "noop": accepts all requests (development only)

    Args:
        config: The SandboxConfig instance.

    Returns:
        The initialized AuthProvider.
    """
    global _provider

    auth_config = config.authentication
    provider_type = auth_config.provider

    if provider_type == "static":
        _provider = StaticKeyAuthProvider(keys=auth_config.static_keys)
    elif provider_type == "remote":
        _provider = RemoteAuthProvider(
            url=auth_config.remote_url,
            timeout=auth_config.remote_timeout,
            headers=auth_config.remote_headers,
        )
    elif provider_type == "noop":
        _provider = NoopAuthProvider()
    else:
        raise ValueError(
            f"Unknown auth provider: '{provider_type}'. "
            f"Supported: 'static', 'remote', 'noop'"
        )

    logger.info(f"Auth provider initialized: {provider_type}")
    return _provider


def get_auth_provider() -> Optional[AuthProvider]:
    """Get the global auth provider instance."""
    return _provider


# Backwards compatibility
get_authenticator = get_auth_provider
