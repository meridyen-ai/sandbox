"""
Base Database Connector

Abstract base class for all database connectors with connection pooling.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, AsyncIterator, Generic, TypeVar

from sandbox.core.config import DatabaseConnectionConfig
from sandbox.core.exceptions import ConnectionError
from sandbox.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")  # Connection type


@dataclass
class QueryResult:
    """Result of a database query."""
    columns: list[str]
    column_types: list[str]
    rows: list[tuple[Any, ...]]
    row_count: int
    affected_rows: int = 0


class BaseConnector(ABC, Generic[T]):
    """
    Abstract base class for database connectors.

    Provides a unified interface for:
    - Connection management
    - Query execution
    - Schema introspection
    """

    def __init__(self, config: DatabaseConnectionConfig) -> None:
        self.config = config
        self._pool: ConnectionPool[T] | None = None
        self._logger = get_logger(f"connector.{config.db_type.value}")

    @property
    def connection_id(self) -> str:
        return self.config.id

    @property
    def db_type(self) -> str:
        return self.config.db_type.value

    @abstractmethod
    async def connect(self) -> T:
        """Create a new connection."""
        pass

    @abstractmethod
    async def close_connection(self, conn: T) -> None:
        """Close a connection."""
        pass

    @abstractmethod
    async def execute(
        self,
        conn: T,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Execute a query and return results."""
        pass

    @abstractmethod
    async def execute_streaming(
        self,
        conn: T,
        query: str,
        parameters: dict[str, Any] | None = None,
        batch_size: int = 1000,
    ) -> AsyncGenerator[list[tuple[Any, ...]], None]:
        """Execute a query and stream results in batches."""
        pass

    @abstractmethod
    async def get_tables(self, conn: T, schema: str | None = None) -> list[str]:
        """Get list of tables in the database."""
        pass

    @abstractmethod
    async def get_columns(
        self, conn: T, table: str, schema: str | None = None
    ) -> list[dict[str, Any]]:
        """Get column information for a table."""
        pass

    @abstractmethod
    async def test_connection(self, conn: T) -> bool:
        """Test if connection is valid."""
        pass

    async def initialize_pool(self, min_size: int = 1, max_size: int = 10) -> None:
        """Initialize connection pool."""
        self._pool = ConnectionPool(
            connector=self,
            min_size=min_size,
            max_size=max_size,
        )
        await self._pool.initialize()
        self._logger.info(
            "connection_pool_initialized",
            connection_id=self.connection_id,
            min_size=min_size,
            max_size=max_size,
        )

    async def close_pool(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._logger.info(
                "connection_pool_closed",
                connection_id=self.connection_id,
            )

    @asynccontextmanager
    async def get_connection(self) -> AsyncIterator[T]:
        """Get a connection from the pool."""
        if self._pool is None:
            # No pool, create single connection
            conn = await self.connect()
            try:
                yield conn
            finally:
                await self.close_connection(conn)
        else:
            async with self._pool.acquire() as conn:
                yield conn

    def _build_connection_string(self) -> str:
        """Build connection string (override in subclasses if needed)."""
        cfg = self.config
        password = cfg.password.get_secret_value() if cfg.password else ""
        return f"{cfg.db_type.value}://{cfg.username}:{password}@{cfg.host}:{cfg.port}/{cfg.database}"

    def _mask_connection_string(self, conn_str: str) -> str:
        """Mask password in connection string for logging."""
        import re
        return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", conn_str)


@dataclass
class ConnectionPool(Generic[T]):
    """
    Async connection pool with automatic scaling.

    Features:
    - Lazy connection creation
    - Connection validation
    - Automatic cleanup of stale connections
    """

    connector: BaseConnector[T]
    min_size: int = 1
    max_size: int = 10
    acquire_timeout: float = 30.0
    connection_timeout: float = 10.0
    idle_timeout: float = 300.0  # 5 minutes

    _available: asyncio.Queue[T] = field(init=False)
    _in_use: set[T] = field(default_factory=set, init=False)
    _size: int = field(default=0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _closed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self._available = asyncio.Queue(maxsize=self.max_size)

    async def initialize(self) -> None:
        """Initialize the pool with minimum connections."""
        for _ in range(self.min_size):
            conn = await self._create_connection()
            await self._available.put(conn)

    async def _create_connection(self) -> T:
        """Create a new connection."""
        async with self._lock:
            if self._size >= self.max_size:
                raise ConnectionError(
                    f"Connection pool exhausted (max={self.max_size})",
                    connection_id=self.connector.connection_id,
                )

            try:
                conn = await asyncio.wait_for(
                    self.connector.connect(),
                    timeout=self.connection_timeout,
                )
                self._size += 1
                return conn
            except asyncio.TimeoutError:
                raise ConnectionError(
                    f"Connection timeout after {self.connection_timeout}s",
                    connection_id=self.connector.connection_id,
                )

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[T]:
        """Acquire a connection from the pool."""
        if self._closed:
            raise ConnectionError(
                "Connection pool is closed",
                connection_id=self.connector.connection_id,
            )

        conn: T | None = None

        try:
            # Try to get from available
            try:
                conn = self._available.get_nowait()
            except asyncio.QueueEmpty:
                # Create new if under max
                if self._size < self.max_size:
                    conn = await self._create_connection()
                else:
                    # Wait for available connection
                    try:
                        conn = await asyncio.wait_for(
                            self._available.get(),
                            timeout=self.acquire_timeout,
                        )
                    except asyncio.TimeoutError:
                        raise ConnectionError(
                            f"Timeout waiting for connection (timeout={self.acquire_timeout}s)",
                            connection_id=self.connector.connection_id,
                        )

            # Validate connection
            if not await self._validate_connection(conn):
                # Connection invalid, create new one
                await self._discard_connection(conn)
                conn = await self._create_connection()

            self._in_use.add(conn)
            yield conn

        finally:
            if conn is not None:
                self._in_use.discard(conn)
                if not self._closed:
                    try:
                        self._available.put_nowait(conn)
                    except asyncio.QueueFull:
                        await self._discard_connection(conn)

    async def _validate_connection(self, conn: T) -> bool:
        """Validate a connection is still usable."""
        try:
            return await asyncio.wait_for(
                self.connector.test_connection(conn),
                timeout=5.0,
            )
        except Exception:
            return False

    async def _discard_connection(self, conn: T) -> None:
        """Discard a connection."""
        async with self._lock:
            self._size -= 1
        try:
            await self.connector.close_connection(conn)
        except Exception:
            pass

    async def close(self) -> None:
        """Close all connections in the pool."""
        self._closed = True

        # Close available connections
        while True:
            try:
                conn = self._available.get_nowait()
                await self.connector.close_connection(conn)
            except asyncio.QueueEmpty:
                break

        # Close in-use connections
        for conn in list(self._in_use):
            try:
                await self.connector.close_connection(conn)
            except Exception:
                pass

        self._in_use.clear()
        self._size = 0

    @property
    def size(self) -> int:
        """Current pool size."""
        return self._size

    @property
    def available_count(self) -> int:
        """Number of available connections."""
        return self._available.qsize()

    @property
    def in_use_count(self) -> int:
        """Number of connections in use."""
        return len(self._in_use)
