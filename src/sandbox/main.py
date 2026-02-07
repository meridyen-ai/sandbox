"""
Sandbox Application Entry Point

Starts both gRPC and REST servers for the sandbox.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from typing import Any

import uvicorn

from sandbox.core.config import get_config
from sandbox.core.logging import setup_logging, get_logger
from sandbox.services.grpc_server import SandboxGRPCServer
from sandbox.services.rest_api import create_rest_app
from sandbox.services.registration import SandboxRegistration


logger = get_logger(__name__)


class SandboxApplication:
    """
    Main sandbox application.

    Manages lifecycle of all services:
    - gRPC server
    - REST API server
    - Registration service
    """

    def __init__(self) -> None:
        self.config = get_config()
        self._grpc_server: SandboxGRPCServer | None = None
        self._rest_server: uvicorn.Server | None = None
        self._registration: SandboxRegistration | None = None
        self._shutdown_event = asyncio.Event()

    async def start(self) -> None:
        """Start all services."""
        setup_logging()
        logger.info(
            "sandbox_starting",
            environment=self.config.environment,
            execution_mode=self.config.execution_mode.value,
        )

        # Setup signal handlers
        self._setup_signal_handlers()

        # Start registration service (if not air-gapped)
        if not self.config.is_airgapped():
            self._registration = SandboxRegistration()
            await self._registration.start()

        # Start gRPC server
        self._grpc_server = SandboxGRPCServer(
            host=self.config.server.host,
            port=self.config.server.grpc_port,
        )
        await self._grpc_server.start()

        # Start REST API server
        rest_app = create_rest_app()
        rest_config = uvicorn.Config(
            app=rest_app,
            host=self.config.server.host,
            port=self.config.server.rest_port,
            log_level="warning",
            access_log=False,
        )
        self._rest_server = uvicorn.Server(rest_config)

        # Run REST server in background
        asyncio.create_task(self._rest_server.serve())

        logger.info(
            "sandbox_started",
            grpc_port=self.config.server.grpc_port,
            rest_port=self.config.server.rest_port,
            sandbox_id=self._registration.sandbox_id if self._registration else None,
        )

        # Wait for shutdown signal
        await self._shutdown_event.wait()

        # Graceful shutdown
        await self.stop()

    async def stop(self) -> None:
        """Stop all services gracefully."""
        logger.info("sandbox_stopping")

        # Stop registration
        if self._registration:
            await self._registration.stop()

        # Stop gRPC server
        if self._grpc_server:
            await self._grpc_server.stop(grace_period=5.0)

        # Stop REST server
        if self._rest_server:
            self._rest_server.should_exit = True

        logger.info("sandbox_stopped")

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        loop = asyncio.get_running_loop()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._signal_handler)

    def _signal_handler(self) -> None:
        """Handle shutdown signal."""
        logger.info("shutdown_signal_received")
        self._shutdown_event.set()


def main() -> None:
    """Main entry point."""
    app = SandboxApplication()

    try:
        asyncio.run(app.start())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error("sandbox_error", error=str(e), exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
