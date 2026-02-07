"""
SQL Execution Engine

Secure SQL execution with:
- Query validation and sanitization
- Timeout enforcement
- Resource limiting
- Result processing and masking
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from sandbox.core.config import get_config, SecurityConfig, ResourceLimitsConfig
from sandbox.core.exceptions import (
    SQLExecutionError,
    SecurityError,
    TimeoutError,
    RowLimitError,
    ValidationError,
)
from sandbox.core.logging import get_logger, log_security_event
from sandbox.execution.base import (
    BaseExecutor,
    ExecutionContext,
    ExecutionMetrics,
    ExecutionResult,
    ExecutionStatus,
)

logger = get_logger(__name__)


@dataclass
class ColumnInfo:
    """Information about a result column."""
    name: str
    data_type: str
    is_masked: bool = False


@dataclass
class SQLExecutionResult(ExecutionResult):
    """Result of SQL execution."""
    columns: list[ColumnInfo] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    total_rows_available: int | None = None  # Total before limit applied
    query_hash: str | None = None  # For caching/deduplication

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update({
            "columns": [
                {"name": c.name, "type": c.data_type, "masked": c.is_masked}
                for c in self.columns
            ],
            "rows": self.rows,
            "row_count": self.row_count,
        })
        if self.total_rows_available is not None:
            result["total_rows_available"] = self.total_rows_available
        return result


class SQLValidator:
    """
    SQL query validator.

    Checks queries for:
    - Allowed statement types (SELECT only by default)
    - Banned patterns (DROP, DELETE, etc.)
    - SQL injection patterns
    """

    # Common SQL injection patterns
    INJECTION_PATTERNS = [
        r";\s*--",  # Statement termination with comment
        r"'\s*OR\s+'?1'?\s*=\s*'?1",  # OR 1=1 injection
        r"'\s*OR\s+''='",  # OR ''='' injection
        r"UNION\s+ALL\s+SELECT",  # UNION injection
        r"INTO\s+OUTFILE",  # File write
        r"INTO\s+DUMPFILE",  # File write
        r"LOAD_FILE",  # File read
        r"@@version",  # Version enumeration
        r"information_schema",  # Schema enumeration
        r"BENCHMARK\s*\(",  # Timing attack
        r"SLEEP\s*\(",  # Timing attack
        r"WAITFOR\s+DELAY",  # Timing attack (MSSQL)
    ]

    def __init__(self, security_config: SecurityConfig | None = None) -> None:
        config = get_config()
        self.security = security_config or config.security
        self._injection_re = re.compile(
            "|".join(self.INJECTION_PATTERNS),
            re.IGNORECASE,
        )

    def validate(self, query: str) -> list[str]:
        """
        Validate a SQL query.

        Returns list of validation errors (empty if valid).
        """
        errors: list[str] = []
        query_upper = query.upper().strip()

        # Check statement type
        allowed = self.security.allowed_sql_statements
        if not any(query_upper.startswith(stmt) for stmt in allowed):
            errors.append(
                f"Only {', '.join(allowed)} statements are allowed"
            )
            log_security_event(
                "blocked_sql_statement",
                statement_type=query_upper.split()[0] if query_upper else "EMPTY",
            )

        # Check banned patterns
        for pattern in self.security.banned_sql_patterns:
            if pattern.upper() in query_upper:
                errors.append(f"Query contains banned pattern: {pattern}")
                log_security_event(
                    "blocked_sql_pattern",
                    pattern=pattern,
                )

        # Check injection patterns
        if self._injection_re.search(query):
            errors.append("Query contains potential SQL injection pattern")
            log_security_event(
                "sql_injection_detected",
            )

        return errors

    def is_read_only(self, query: str) -> bool:
        """Check if query is read-only (SELECT/WITH only)."""
        query_upper = query.upper().strip()
        return query_upper.startswith("SELECT") or query_upper.startswith("WITH")


class DataMasker:
    """
    Data masking for sensitive columns.

    Masks values in columns that match sensitive patterns.
    """

    def __init__(self, security_config: SecurityConfig | None = None) -> None:
        config = get_config()
        self.security = security_config or config.security
        self._patterns = [
            self._pattern_to_regex(p)
            for p in self.security.sensitive_column_patterns
        ]

    @staticmethod
    def _pattern_to_regex(pattern: str) -> re.Pattern[str]:
        """Convert glob-like pattern to regex."""
        # Escape special chars except *
        escaped = re.escape(pattern).replace(r"\*", ".*")
        return re.compile(f"^{escaped}$", re.IGNORECASE)

    def is_sensitive_column(self, column_name: str) -> bool:
        """Check if column name matches sensitive patterns."""
        return any(p.match(column_name) for p in self._patterns)

    def mask_value(self, value: Any, column_name: str) -> Any:
        """Mask a single value if column is sensitive."""
        if not self.security.mask_sensitive_data:
            return value
        if not self.is_sensitive_column(column_name):
            return value
        return self._apply_mask(value)

    def _apply_mask(self, value: Any) -> str:
        """Apply masking to a value."""
        if value is None:
            return None
        if isinstance(value, str):
            if len(value) <= 4:
                return "****"
            # Show first and last char with middle masked
            return f"{value[0]}{'*' * (len(value) - 2)}{value[-1]}"
        # For non-strings, just return masked placeholder
        return "***MASKED***"

    def mask_rows(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
    ) -> tuple[list[dict[str, Any]], set[str]]:
        """
        Mask sensitive values in rows.

        Returns (masked_rows, set of masked column names).
        """
        if not self.security.mask_sensitive_data:
            return rows, set()

        sensitive_cols = {c for c in columns if self.is_sensitive_column(c)}
        if not sensitive_cols:
            return rows, set()

        masked_rows = []
        for row in rows:
            masked_row = {}
            for key, value in row.items():
                if key in sensitive_cols:
                    masked_row[key] = self._apply_mask(value)
                else:
                    masked_row[key] = value
            masked_rows.append(masked_row)

        return masked_rows, sensitive_cols


class SQLExecutor(BaseExecutor[SQLExecutionResult]):
    """
    SQL Execution Engine.

    Executes SQL queries against configured database connections
    with security validation, timeout enforcement, and result processing.
    """

    def __init__(
        self,
        config: ResourceLimitsConfig | None = None,
        security_config: SecurityConfig | None = None,
    ) -> None:
        super().__init__(config)
        self.validator = SQLValidator(security_config)
        self.masker = DataMasker(security_config)
        self._connection_pool: dict[str, Any] = {}

    async def validate(self, context: ExecutionContext, **kwargs: Any) -> list[str]:
        """Validate SQL execution request."""
        errors: list[str] = []

        query = kwargs.get("query")
        if not query:
            errors.append("Query is required")
            return errors

        if not isinstance(query, str):
            errors.append("Query must be a string")
            return errors

        # Validate query content
        errors.extend(self.validator.validate(query))

        # Validate connection
        connection_id = context.connection_id
        if not connection_id:
            errors.append("Connection ID is required")

        return errors

    async def execute(
        self,
        context: ExecutionContext,
        *,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> SQLExecutionResult:
        """
        Execute a SQL query.

        Args:
            context: Execution context
            query: SQL query to execute
            parameters: Query parameters (for parameterized queries)

        Returns:
            SQLExecutionResult with query results
        """
        metrics = ExecutionMetrics()
        self._log_start(context, "sql", query_preview=query[:100])

        try:
            # Get connection
            connection = await self._get_connection(context.connection_id)

            # Execute with timeout
            timeout = context.get_timeout(self.config)
            max_rows = context.get_max_rows(self.config)

            try:
                rows, columns = await asyncio.wait_for(
                    self._execute_query(connection, query, parameters, max_rows),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                raise TimeoutError(
                    f"Query execution timed out after {timeout} seconds",
                    timeout_seconds=timeout,
                    execution_type="sql",
                )

            # Process results
            masked_rows, masked_cols = self.masker.mask_rows(
                rows, [c.name for c in columns]
            )

            # Update column info with masking status
            for col in columns:
                col.is_masked = col.name in masked_cols

            # Check row limit
            if len(masked_rows) > max_rows:
                total_available = len(masked_rows)
                masked_rows = masked_rows[:max_rows]
                logger.warning(
                    "row_limit_applied",
                    request_id=context.request_id,
                    total_rows=total_available,
                    returned_rows=max_rows,
                )
            else:
                total_available = None

            metrics.complete()
            metrics.rows_returned = len(masked_rows)
            metrics.rows_processed = len(rows)

            result = SQLExecutionResult(
                request_id=context.request_id,
                status=ExecutionStatus.SUCCESS,
                metrics=metrics,
                columns=columns,
                rows=masked_rows,
                row_count=len(masked_rows),
                total_rows_available=total_available,
            )

            self._log_complete(context, result, "sql", rows_returned=len(masked_rows))
            return result

        except TimeoutError:
            raise
        except SecurityError:
            raise
        except Exception as e:
            metrics.complete()
            self._log_error(context, e, "sql")
            raise SQLExecutionError(
                f"SQL execution failed: {e}",
                query=query,
                cause=e,
            )

    async def _get_connection(self, connection_id: str | None) -> Any:
        """Get database connection from pool."""
        if not connection_id:
            raise ValidationError("Connection ID is required")

        # Check cache
        if connection_id in self._connection_pool:
            return self._connection_pool[connection_id]

        # Get connection config
        config = get_config()
        conn_config = config.get_connection(connection_id)
        if not conn_config:
            raise ValidationError(f"Connection not found: {connection_id}")

        # Create connection based on database type
        connection = await self._create_connection(conn_config)
        self._connection_pool[connection_id] = connection
        return connection

    async def _create_connection(self, conn_config: Any) -> Any:
        """Create a new database connection."""
        from sandbox.connectors import get_connector

        connector = get_connector(conn_config.db_type)
        return await connector.connect(conn_config)

    async def _execute_query(
        self,
        connection: Any,
        query: str,
        parameters: dict[str, Any] | None,
        max_rows: int,
    ) -> tuple[list[dict[str, Any]], list[ColumnInfo]]:
        """Execute query and return results with column info."""
        # This is a simplified implementation
        # The actual implementation depends on the database driver
        cursor = await connection.execute(query, parameters or {})

        # Get column information
        columns = [
            ColumnInfo(
                name=desc[0],
                data_type=str(desc[1]) if len(desc) > 1 else "unknown",
            )
            for desc in cursor.description or []
        ]

        # Fetch rows as dictionaries
        rows = []
        column_names = [c.name for c in columns]
        async for row in cursor:
            if len(rows) >= max_rows + 1:  # Fetch one extra to detect truncation
                break
            rows.append(dict(zip(column_names, row)))

        return rows, columns

    async def close(self) -> None:
        """Close all connections in the pool."""
        for connection in self._connection_pool.values():
            try:
                await connection.close()
            except Exception as e:
                logger.warning("connection_close_error", error=str(e))
        self._connection_pool.clear()
