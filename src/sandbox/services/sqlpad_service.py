"""
SQL Pad Integration Service

Manages SQL Pad connections and authentication for seamless database exploration.
"""

from __future__ import annotations

import os
from typing import Any
import httpx
from datetime import datetime, timedelta

from sandbox.core.config import get_config
from sandbox.core.exceptions import SandboxError
from sandbox.core.logging import get_logger

logger = get_logger(__name__)


class SQLPadService:
    """Service for managing SQL Pad integration."""

    def __init__(self):
        self.config = get_config()
        self.sqlpad_url = os.getenv("SQLPAD_URL", "http://sqlpad:3000")
        self.sqlpad_admin = os.getenv("SQLPAD_ADMIN", "admin@meridyen.local")
        self.sqlpad_password = os.getenv("SQLPAD_ADMIN_PASSWORD", "admin")
        self.service_token_secret = os.getenv("SQLPAD_SERVICE_TOKEN_SECRET", "")
        self._client = httpx.AsyncClient(timeout=30.0)
        self._authenticated = False
        self._auth_expires: datetime | None = None
        # Cached service token for embedding
        self._service_token: str | None = None
        self._service_token_expires: datetime | None = None

    async def _ensure_authenticated(self) -> None:
        """Ensure the httpx client has a valid session cookie."""
        now = datetime.utcnow()

        if self._authenticated and self._auth_expires and now < self._auth_expires:
            return

        # Authenticate with SQL Pad (v7 uses cookie-based sessions)
        try:
            response = await self._client.post(
                f"{self.sqlpad_url}/api/signin",
                json={
                    "email": self.sqlpad_admin,
                    "password": self.sqlpad_password,
                }
            )
            response.raise_for_status()

            # SQL Pad v7 sets session cookie automatically on the httpx client
            self._authenticated = True
            self._auth_expires = now + timedelta(hours=23)

            logger.info("sqlpad_authenticated")

        except Exception as e:
            logger.error("sqlpad_auth_failed", error=str(e))
            raise SandboxError(f"Failed to authenticate with SQL Pad: {e}")

    async def _get_service_token(self) -> str:
        """Get or create a service token for auto-login in embedded iframe."""
        now = datetime.utcnow()

        if self._service_token and self._service_token_expires and now < self._service_token_expires:
            return self._service_token

        await self._ensure_authenticated()

        try:
            # Create a service token via SQL Pad API (duration is in days, max 730)
            response = await self._client.post(
                f"{self.sqlpad_url}/api/service-tokens",
                json={
                    "name": f"sandbox-embed-{now.strftime('%Y%m%d%H%M%S')}",
                    "role": "editor",
                    "duration": 30,  # 30 days
                }
            )
            response.raise_for_status()
            data = response.json()

            self._service_token = data.get("token")
            self._service_token_expires = now + timedelta(days=29)

            logger.info("sqlpad_service_token_created")
            return self._service_token

        except Exception as e:
            logger.warning("sqlpad_service_token_failed", error=str(e))
            # Fallback: return empty string (user will see login form)
            return ""

    async def create_or_update_connection(
        self,
        connection_id: str,
        name: str,
        db_type: str,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        schema: str | None = None,
    ) -> dict[str, Any]:
        """
        Create or update a connection in SQL Pad.

        Args:
            connection_id: Unique connection ID
            name: Display name
            db_type: Database type (postgres, mysql, sqlserver, etc.)
            host: Database host
            port: Database port
            database: Database name
            username: Database username
            password: Database password
            schema: Optional schema name

        Returns:
            SQL Pad connection object
        """
        await self._ensure_authenticated()

        # Map sandbox db types to SQL Pad driver names
        driver_map = {
            "postgres": "postgres",
            "postgresql": "postgres",
            "mysql": "mysql",
            "sqlserver": "sqlserver",
            "mssql": "sqlserver",
            "snowflake": "snowflake",
            "bigquery": "bigquery",
            "redshift": "postgres",  # Redshift uses postgres driver
            "oracle": "oracle",
            "sap_hana": "hana",
            "trino": "trino",
        }

        driver = driver_map.get(db_type.lower(), "postgres")

        connection_data = {
            "name": name,
            "driver": driver,
            "multiStatementTransactionEnabled": True,
            "idleTimeoutSeconds": 3600,
        }

        # Add connection-specific fields based on driver
        if driver in ["postgres", "mysql"]:
            connection_data.update({
                "host": host,
                "port": str(port),
                "database": database,
                "username": username,
                "password": password,
            })
            if schema and driver == "postgres":
                connection_data["postgresSslmode"] = "prefer"
                connection_data["postgresSchema"] = schema
        else:
            # Build connection string for other drivers
            connection_data["connectionString"] = (
                f"{driver}://{username}:{password}@{host}:{port}/{database}"
            )

        try:
            # List existing connections and find by name
            list_resp = await self._client.get(
                f"{self.sqlpad_url}/api/connections"
            )
            list_resp.raise_for_status()
            existing = list_resp.json()

            # Find existing connection matching this name
            existing_conn = next(
                (c for c in existing if c.get("name") == name),
                None
            )

            if existing_conn:
                # Update existing connection
                response = await self._client.put(
                    f"{self.sqlpad_url}/api/connections/{existing_conn['id']}",
                    json=connection_data
                )
            else:
                # Create new connection
                response = await self._client.post(
                    f"{self.sqlpad_url}/api/connections",
                    json=connection_data
                )

            response.raise_for_status()
            result = response.json()

            logger.info(
                "sqlpad_connection_created",
                connection_id=connection_id,
                name=name,
                driver=driver
            )

            return result

        except Exception as e:
            logger.error("sqlpad_connection_failed", error=str(e))
            raise SandboxError(f"Failed to create SQL Pad connection: {e}")

    async def delete_connection(self, connection_id: str) -> None:
        """Delete a connection from SQL Pad."""
        await self._ensure_authenticated()

        try:
            response = await self._client.delete(
                f"{self.sqlpad_url}/api/connections/{connection_id}",
            )
            response.raise_for_status()

            logger.info("sqlpad_connection_deleted", connection_id=connection_id)

        except Exception as e:
            logger.error("sqlpad_connection_delete_failed", error=str(e))
            raise SandboxError(f"Failed to delete SQL Pad connection: {e}")

    async def list_connections(self) -> list[dict[str, Any]]:
        """List all SQL Pad connections."""
        await self._ensure_authenticated()

        try:
            response = await self._client.get(
                f"{self.sqlpad_url}/api/connections",
            )
            response.raise_for_status()

            return response.json()

        except Exception as e:
            logger.error("sqlpad_list_connections_failed", error=str(e))
            raise SandboxError(f"Failed to list SQL Pad connections: {e}")

    async def get_embed_url(self, connection_id: str | None = None) -> str:
        """
        Get SQL Pad embed URL with auto-authentication via service token.

        Generates a service token so users don't need to log in separately.

        Args:
            connection_id: Optional connection to pre-select

        Returns:
            URL for embedding SQL Pad with auto-login
        """
        public_sqlpad_url = os.getenv("SQLPAD_PUBLIC_URL", "http://localhost:3010")

        params = []

        # Add service token for auto-authentication
        if self.service_token_secret:
            token = await self._get_service_token()
            if token:
                params.append(f"token={token}")

        if connection_id:
            # Find the SQL Pad internal connection ID
            await self._ensure_authenticated()
            try:
                list_resp = await self._client.get(
                    f"{self.sqlpad_url}/api/connections"
                )
                list_resp.raise_for_status()
                connections = list_resp.json()
                # Map sandbox connection name to sqlpad connection ID
                for conn in connections:
                    if conn.get("id"):
                        params.append(f"connectionId={conn['id']}")
                        break
            except Exception:
                pass

        query = "&".join(params)
        return f"{public_sqlpad_url}{'?' + query if query else ''}"

    async def close(self) -> None:
        """Close HTTP client."""
        await self._client.aclose()


# Singleton instance
_sqlpad_service: SQLPadService | None = None


def get_sqlpad_service() -> SQLPadService:
    """Get or create SQL Pad service instance."""
    global _sqlpad_service
    if _sqlpad_service is None:
        _sqlpad_service = SQLPadService()
    return _sqlpad_service
