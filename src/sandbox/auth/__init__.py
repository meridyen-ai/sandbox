"""
Authentication providers for Meridyen Sandbox.

Supports pluggable authentication backends:
- StaticKeyAuthProvider: validates against keys in config (default)
- RemoteAuthProvider: validates via external HTTP endpoint
- NoopAuthProvider: accepts all requests (development only)
"""

from sandbox.auth.base import AuthProvider, AuthResult
from sandbox.auth.providers import (
    NoopAuthProvider,
    RemoteAuthProvider,
    StaticKeyAuthProvider,
)
from sandbox.auth.sandbox_auth import get_auth_provider, initialize_auth_provider

__all__ = [
    "AuthProvider",
    "AuthResult",
    "StaticKeyAuthProvider",
    "RemoteAuthProvider",
    "NoopAuthProvider",
    "initialize_auth_provider",
    "get_auth_provider",
]
