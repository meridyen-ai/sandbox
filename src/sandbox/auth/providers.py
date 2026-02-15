"""
Built-in authentication providers.

Three providers cover common deployment scenarios:
- StaticKeyAuthProvider: standalone deployments with keys in config
- RemoteAuthProvider: integration with external auth systems via HTTP
- NoopAuthProvider: development and testing (no auth)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from sandbox.auth.base import AuthProvider, AuthResult

logger = logging.getLogger(__name__)


class StaticKeyAuthProvider(AuthProvider):
    """
    Validates API keys against a static list configured via YAML/env.

    Config example (sandbox.yaml):
        authentication:
          provider: static
          static_keys:
            - key: "sb_my-secret-key-here"
              workspace_id: "ws_1"
              workspace_name: "Default Workspace"
              permissions:
                execute_sql: true
                execute_python: true
    """

    def __init__(self, keys: list[dict[str, Any]]) -> None:
        self._keys: dict[str, dict[str, Any]] = {}
        for key_config in keys:
            raw_key = key_config["key"]
            self._keys[raw_key] = key_config
        logger.info(f"Static auth provider initialized with {len(keys)} key(s)")

    async def verify(self, api_key: str) -> AuthResult | None:
        key_config = self._keys.get(api_key)
        if not key_config:
            return None

        return AuthResult(
            authenticated=True,
            workspace_id=str(key_config.get("workspace_id", "default")),
            workspace_name=key_config.get("workspace_name", "Default"),
            user_id=key_config.get("user_id"),
            api_key_name=key_config.get("name", "static-key"),
            permissions=key_config.get("permissions", {}),
        )


class RemoteAuthProvider(AuthProvider):
    """
    Validates API keys by calling an external HTTP endpoint.

    The remote endpoint receives POST {"api_key": "..."} and must return:
      {"valid": true, "workspace_id": "...", ...} or {"valid": false}

    Config example (sandbox.yaml):
        authentication:
          provider: remote
          remote_url: "https://your-api.com/auth/validate-key"
          remote_timeout: 5.0
          remote_headers:
            X-Service-Token: "internal-token"
    """

    def __init__(
        self,
        url: str,
        timeout: float = 5.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._url = url
        self._timeout = timeout
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers=headers or {},
        )
        logger.info(f"Remote auth provider initialized: {url}")

    async def verify(self, api_key: str) -> AuthResult | None:
        try:
            response = await self._client.post(
                self._url,
                json={"api_key": api_key},
                headers={"Content-Type": "application/json"},
            )

            if response.status_code != 200:
                logger.warning(f"Remote auth returned status {response.status_code}")
                return None

            data = response.json()

            if not data.get("valid"):
                return None

            return AuthResult(
                authenticated=True,
                workspace_id=str(data.get("workspace_id", "")),
                workspace_name=data.get("workspace_name"),
                user_id=str(data.get("user_id", "")) if data.get("user_id") else None,
                api_key_name=data.get("api_key_name"),
                permissions=data.get("permissions", {}),
            )

        except httpx.TimeoutException:
            logger.error(f"Timeout calling remote auth endpoint: {self._url}")
            return None
        except httpx.RequestError as e:
            logger.error(f"Error calling remote auth: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error in remote auth: {e}", exc_info=True)
            return None

    async def close(self) -> None:
        await self._client.aclose()

    async def health_check(self) -> bool:
        try:
            # Try a health endpoint at the same base path
            base_url = self._url.rsplit("/", 1)[0]
            response = await self._client.get(f"{base_url}/health")
            return response.status_code == 200
        except Exception:
            return False


class NoopAuthProvider(AuthProvider):
    """
    Accepts all requests without validation. Development only.

    WARNING: Never use in production.

    Config example:
        authentication:
          provider: noop
    """

    def __init__(self) -> None:
        logger.warning(
            "NoopAuthProvider active - ALL requests accepted without authentication"
        )

    async def verify(self, api_key: str) -> AuthResult | None:
        return AuthResult(
            authenticated=True,
            workspace_id="dev",
            workspace_name="Development",
            permissions={
                "execute_sql": True,
                "execute_python": True,
                "generate_visualizations": True,
            },
        )
