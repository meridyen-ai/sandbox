"""
Sandbox Registration Service

Handles registration with Core Platform and heartbeat mechanism.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

from sandbox.core.config import get_config
from sandbox.core.exceptions import ConnectionError, AuthenticationError
from sandbox.core.logging import get_logger

logger = get_logger(__name__)


class SandboxRegistration:
    """
    Manages sandbox registration with Core Platform.

    Features:
    - Initial registration with capabilities
    - Periodic heartbeat
    - Reconnection with exponential backoff
    - Command handling from platform
    """

    def __init__(self) -> None:
        self.config = get_config()
        self._sandbox_id: str | None = self.config.platform.sandbox_id
        self._registered = False
        self._heartbeat_task: asyncio.Task | None = None
        self._command_handlers: dict[str, Callable] = {}
        self._http_client: httpx.AsyncClient | None = None
        self._logger = get_logger("registration")

    @property
    def sandbox_id(self) -> str | None:
        """Get the sandbox ID."""
        return self._sandbox_id

    @property
    def is_registered(self) -> bool:
        """Check if sandbox is registered."""
        return self._registered

    async def start(self) -> None:
        """Start the registration service."""
        # Create HTTP client
        self._http_client = httpx.AsyncClient(
            base_url=self.config.platform.platform_url,
            timeout=30.0,
        )

        # Register with platform
        await self._register()

        # Start heartbeat
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        self._logger.info(
            "registration_service_started",
            sandbox_id=self._sandbox_id,
            platform_url=self.config.platform.platform_url,
        )

    async def stop(self) -> None:
        """Stop the registration service."""
        # Cancel heartbeat
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # Unregister
        if self._registered:
            await self._unregister()

        # Close HTTP client
        if self._http_client:
            await self._http_client.aclose()

        self._logger.info("registration_service_stopped")

    async def _register(self) -> None:
        """Register sandbox with Core Platform."""
        from sandbox.connectors.factory import get_available_connectors

        # Generate sandbox ID if not set
        if not self._sandbox_id:
            self._sandbox_id = f"sandbox-{uuid.uuid4().hex[:12]}"

        # Build registration payload
        payload = {
            "workspace_id": self.config.platform.workspace_id,
            "registration_token": self.config.platform.registration_token.get_secret_value()
            if self.config.platform.registration_token
            else None,
            "sandbox_id": self._sandbox_id,
            "version": "1.0.0",
            "callback_url": f"grpc://{self.config.server.host}:{self.config.server.grpc_port}",
            "capabilities": {
                "supported_databases": get_available_connectors(),
                "supported_packages": list(self.config.security.allowed_python_imports),
                "resource_limits": {
                    "max_memory_mb": self.config.resource_limits.max_memory_mb,
                    "max_cpu_seconds": self.config.resource_limits.max_cpu_seconds,
                    "max_rows": self.config.resource_limits.max_rows,
                    "max_concurrent_queries": self.config.resource_limits.max_concurrent_queries,
                },
                "has_local_llm": self.config.local_llm.enabled,
                "local_llm_model": self.config.local_llm.model_name
                if self.config.local_llm.enabled
                else None,
            },
        }

        # Attempt registration with retries
        max_attempts = self.config.platform.reconnect_max_attempts
        backoff = self.config.platform.reconnect_backoff_seconds

        for attempt in range(max_attempts):
            try:
                response = await self._http_client.post(
                    "/api/v1/sandboxes/register",
                    json=payload,
                )

                if response.status_code == 200:
                    data = response.json()
                    self._sandbox_id = data.get("sandbox_id", self._sandbox_id)
                    self._registered = True

                    self._logger.info(
                        "sandbox_registered",
                        sandbox_id=self._sandbox_id,
                        attempt=attempt + 1,
                    )
                    return

                elif response.status_code == 401:
                    raise AuthenticationError("Invalid registration token")

                else:
                    self._logger.warning(
                        "registration_failed",
                        status_code=response.status_code,
                        attempt=attempt + 1,
                        response=response.text[:200],
                    )

            except httpx.RequestError as e:
                self._logger.warning(
                    "registration_error",
                    error=str(e),
                    attempt=attempt + 1,
                )

            # Wait before retry
            if attempt < max_attempts - 1:
                wait_time = backoff * (2 ** attempt)  # Exponential backoff
                self._logger.info(
                    "registration_retry",
                    wait_seconds=wait_time,
                    attempt=attempt + 2,
                )
                await asyncio.sleep(wait_time)

        raise ConnectionError(
            f"Failed to register sandbox after {max_attempts} attempts",
            details={"platform_url": self.config.platform.platform_url},
        )

    async def _unregister(self) -> None:
        """Unregister sandbox from Core Platform."""
        if not self._registered or not self._sandbox_id:
            return

        try:
            await self._http_client.post(
                "/api/v1/sandboxes/unregister",
                json={
                    "sandbox_id": self._sandbox_id,
                    "reason": "shutdown",
                },
            )
            self._registered = False
            self._logger.info("sandbox_unregistered", sandbox_id=self._sandbox_id)

        except Exception as e:
            self._logger.warning("unregister_failed", error=str(e))

    async def _heartbeat_loop(self) -> None:
        """Periodic heartbeat to maintain registration."""
        interval = self.config.platform.heartbeat_interval_seconds

        while True:
            try:
                await asyncio.sleep(interval)

                if not self._registered:
                    # Try to re-register
                    await self._register()
                    continue

                # Send heartbeat
                await self._send_heartbeat()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error("heartbeat_error", error=str(e))
                self._registered = False

    async def _send_heartbeat(self) -> None:
        """Send heartbeat to Core Platform."""
        import psutil

        try:
            # Gather metrics
            cpu_percent = psutil.cpu_percent()
            memory = psutil.virtual_memory()

            payload = {
                "sandbox_id": self._sandbox_id,
                "status": "healthy",
                "metrics": {
                    "cpu_usage_percent": cpu_percent,
                    "memory_usage_percent": memory.percent,
                    "active_queries": 0,  # TODO: Track active queries
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            response = await self._http_client.post(
                "/api/v1/sandboxes/heartbeat",
                json=payload,
            )

            if response.status_code == 200:
                data = response.json()

                # Process commands from platform
                commands = data.get("commands", [])
                for cmd in commands:
                    await self._handle_command(cmd)

            elif response.status_code == 401:
                self._logger.warning("heartbeat_auth_failed")
                self._registered = False

            else:
                self._logger.warning(
                    "heartbeat_failed",
                    status_code=response.status_code,
                )

        except httpx.RequestError as e:
            self._logger.warning("heartbeat_error", error=str(e))
            self._registered = False

    async def _handle_command(self, command: dict[str, Any]) -> None:
        """Handle command from Core Platform."""
        cmd_type = command.get("type")
        cmd_id = command.get("command_id")
        payload = command.get("payload", {})

        self._logger.info(
            "command_received",
            command_id=cmd_id,
            command_type=cmd_type,
        )

        # Check for registered handler
        handler = self._command_handlers.get(cmd_type)
        if handler:
            try:
                await handler(payload)
            except Exception as e:
                self._logger.error(
                    "command_handler_error",
                    command_id=cmd_id,
                    error=str(e),
                )
            return

        # Built-in command handlers
        if cmd_type == "reload_config":
            from sandbox.core.config import reset_config
            reset_config()
            self._logger.info("config_reloaded")

        elif cmd_type == "clear_cache":
            # Clear any caches
            self._logger.info("cache_cleared")

        elif cmd_type == "shutdown":
            self._logger.warning("shutdown_requested")
            # Trigger graceful shutdown
            import signal
            import os
            os.kill(os.getpid(), signal.SIGTERM)

        else:
            self._logger.warning("unknown_command", command_type=cmd_type)

    def register_command_handler(
        self, command_type: str, handler: Callable[[dict[str, Any]], Any]
    ) -> None:
        """Register a custom command handler."""
        self._command_handlers[command_type] = handler

    async def get_platform_config(self) -> dict[str, Any] | None:
        """Fetch configuration from Core Platform."""
        if not self._registered:
            return None

        try:
            response = await self._http_client.get(
                f"/api/v1/sandboxes/{self._sandbox_id}/config",
            )

            if response.status_code == 200:
                return response.json()

        except Exception as e:
            self._logger.error("get_config_failed", error=str(e))

        return None
