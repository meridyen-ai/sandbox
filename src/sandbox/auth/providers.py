"""
Built-in authentication providers.

Three providers cover common deployment scenarios:
- StaticKeyAuthProvider: standalone deployments with keys in config
- RemoteAuthProvider: integration with external auth systems via HTTP
- NoopAuthProvider: development and testing (no auth)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
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
        # 1. Check in-memory static keys (from YAML config)
        key_config = self._keys.get(api_key)
        if key_config:
            return AuthResult(
                authenticated=True,
                workspace_id=str(key_config.get("workspace_id", "default")),
                workspace_name=key_config.get("workspace_name", "Default"),
                user_id=key_config.get("user_id"),
                api_key_name=key_config.get("name", "static-key"),
                permissions=key_config.get("permissions", {}),
            )

        # 2. Check database-stored keys (created via UI)
        return self._check_db_key(api_key)

    def _check_db_key(self, api_key: str) -> AuthResult | None:
        """Check if the API key exists in the PostgreSQL api_keys table."""
        try:
            from sqlalchemy import create_engine, text

            host = os.environ.get("SANDBOX_UPLOAD_DB_HOST", "sandbox-postgres")
            port = int(os.environ.get("SANDBOX_UPLOAD_DB_PORT", "5432"))
            db = os.environ.get("SANDBOX_UPLOAD_DB_NAME", "sandbox_uploads")
            user = os.environ.get("SANDBOX_UPLOAD_DB_USER", "sandbox")
            password = os.environ.get("SANDBOX_UPLOAD_DB_PASSWORD", "sandbox_password")
            url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"

            engine = create_engine(url, pool_pre_ping=True, pool_size=2)
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()

            with engine.connect() as conn:
                result = conn.execute(
                    text("SELECT name, workspace_id, workspace_name, permissions FROM api_keys WHERE key_hash = :key_hash"),
                    {"key_hash": key_hash},
                )
                row = result.fetchone()

            if not row:
                return None

            permissions = row[3] if row[3] else {}
            if isinstance(permissions, str):
                permissions = json.loads(permissions)

            return AuthResult(
                authenticated=True,
                workspace_id=str(row[1]),
                workspace_name=row[2],
                api_key_name=row[0],
                permissions=permissions,
            )
        except Exception as e:
            logger.warning(f"Failed to check DB key: {e}")
            return None


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
