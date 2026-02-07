"""
Connector Factory

Provides factory functions for creating database connectors.
"""

from __future__ import annotations

from typing import Type

from sandbox.connectors.base import BaseConnector
from sandbox.core.config import DatabaseConnectionConfig, DatabaseType
from sandbox.core.exceptions import ConfigurationError
from sandbox.core.logging import get_logger

logger = get_logger(__name__)

# Registry of connector classes
_CONNECTOR_REGISTRY: dict[DatabaseType, Type[BaseConnector]] = {}


def register_connector(db_type: DatabaseType, connector_class: Type[BaseConnector]) -> None:
    """
    Register a connector class for a database type.

    Args:
        db_type: Database type enum value
        connector_class: Connector class to register
    """
    _CONNECTOR_REGISTRY[db_type] = connector_class
    logger.debug("connector_registered", db_type=db_type.value, connector=connector_class.__name__)


def get_connector(
    db_type: DatabaseType | str,
    config: DatabaseConnectionConfig | None = None,
) -> BaseConnector:
    """
    Get a connector instance for the specified database type.

    Args:
        db_type: Database type (enum or string)
        config: Database connection configuration

    Returns:
        Configured connector instance

    Raises:
        ConfigurationError: If database type is not supported
    """
    # Convert string to enum if needed
    if isinstance(db_type, str):
        try:
            db_type = DatabaseType(db_type.lower())
        except ValueError:
            raise ConfigurationError(
                f"Unsupported database type: {db_type}",
                config_key="db_type",
            )

    # Get connector class from registry
    connector_class = _CONNECTOR_REGISTRY.get(db_type)

    if connector_class is None:
        # Try to load connector dynamically
        connector_class = _load_connector(db_type)

        if connector_class is None:
            raise ConfigurationError(
                f"No connector available for database type: {db_type.value}",
                config_key="db_type",
            )

    if config is None:
        raise ConfigurationError(
            "Database connection configuration is required",
            config_key="config",
        )

    return connector_class(config)


def _load_connector(db_type: DatabaseType) -> Type[BaseConnector] | None:
    """
    Dynamically load a connector for the given database type.

    This allows connectors to be loaded on-demand without importing
    all database drivers at startup.
    """
    try:
        if db_type == DatabaseType.POSTGRESQL:
            from sandbox.connectors.postgresql import PostgreSQLConnector
            register_connector(db_type, PostgreSQLConnector)
            return PostgreSQLConnector

        elif db_type == DatabaseType.MYSQL:
            from sandbox.connectors.mysql import MySQLConnector
            register_connector(db_type, MySQLConnector)
            return MySQLConnector

        elif db_type == DatabaseType.SNOWFLAKE:
            # Snowflake connector (optional dependency)
            try:
                from sandbox.connectors.snowflake import SnowflakeConnector
                register_connector(db_type, SnowflakeConnector)
                return SnowflakeConnector
            except ImportError:
                logger.warning(
                    "snowflake_connector_not_available",
                    message="Install snowflake-connector-python to use Snowflake",
                )
                return None

        elif db_type == DatabaseType.BIGQUERY:
            # BigQuery connector (optional dependency)
            try:
                from sandbox.connectors.bigquery import BigQueryConnector
                register_connector(db_type, BigQueryConnector)
                return BigQueryConnector
            except ImportError:
                logger.warning(
                    "bigquery_connector_not_available",
                    message="Install google-cloud-bigquery to use BigQuery",
                )
                return None

        elif db_type == DatabaseType.MSSQL:
            # MSSQL connector
            try:
                from sandbox.connectors.mssql import MSSQLConnector
                register_connector(db_type, MSSQLConnector)
                return MSSQLConnector
            except ImportError:
                logger.warning(
                    "mssql_connector_not_available",
                    message="Install pymssql to use MSSQL",
                )
                return None

        else:
            logger.warning(
                "connector_not_implemented",
                db_type=db_type.value,
            )
            return None

    except Exception as e:
        logger.error(
            "connector_load_failed",
            db_type=db_type.value,
            error=str(e),
        )
        return None


def get_available_connectors() -> list[str]:
    """
    Get list of available database connectors.

    Returns:
        List of database type names that have connectors available
    """
    available = []

    for db_type in DatabaseType:
        try:
            _load_connector(db_type)
            if db_type in _CONNECTOR_REGISTRY:
                available.append(db_type.value)
        except Exception:
            pass

    return available


# Pre-register core connectors
try:
    from sandbox.connectors.postgresql import PostgreSQLConnector
    register_connector(DatabaseType.POSTGRESQL, PostgreSQLConnector)
except ImportError:
    pass

try:
    from sandbox.connectors.mysql import MySQLConnector
    register_connector(DatabaseType.MYSQL, MySQLConnector)
except ImportError:
    pass
