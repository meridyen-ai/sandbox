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


# Where each database type's connector lives: (module, class). A module is
# imported the first time its type is asked for, so a sandbox does not load
# every driver at startup.
_CONNECTORS: dict[DatabaseType, tuple[str, str]] = {
    DatabaseType.POSTGRESQL: ("postgresql", "PostgreSQLConnector"),
    DatabaseType.COCKROACHDB: ("postgresql", "PostgreSQLConnector"),
    DatabaseType.MYSQL: ("mysql", "MySQLConnector"),
    DatabaseType.MARIADB: ("mysql", "MySQLConnector"),
    DatabaseType.SINGLESTORE: ("mysql", "MySQLConnector"),
    DatabaseType.MSSQL: ("mssql", "MSSQLConnector"),
    DatabaseType.AZURESYNAPSE: ("mssql", "MSSQLConnector"),
    DatabaseType.SAPHANA: ("saphana", "SAPHANAConnector"),
    DatabaseType.ORACLE: ("oracle", "OracleConnector"),
    DatabaseType.TERADATA: ("teradata", "TeradataConnector"),
    DatabaseType.CLICKHOUSE: ("clickhouse", "ClickHouseConnector"),
    DatabaseType.SNOWFLAKE: ("snowflake", "SnowflakeConnector"),
    DatabaseType.BIGQUERY: ("bigquery", "BigQueryConnector"),
    DatabaseType.REDSHIFT: ("redshift", "RedshiftConnector"),
    DatabaseType.DATABRICKS: ("databricks", "DatabricksConnector"),
    DatabaseType.ATHENA: ("athena", "AthenaConnector"),
    DatabaseType.TRINO: ("trino", "TrinoConnector"),
    DatabaseType.STARBURST: ("trino", "StarburstConnector"),
    DatabaseType.PRESTO: ("trino", "PrestoConnector"),
    DatabaseType.DREMIO: ("dremio", "DremioConnector"),
    DatabaseType.DENODO: ("denodo", "DenodoConnector"),
}


def _load_connector(db_type: DatabaseType) -> Type[BaseConnector] | None:
    """
    Dynamically load a connector for the given database type.

    This allows connectors to be loaded on-demand without importing
    all database drivers at startup. None when the sandbox has no connector
    for the type, or when the connector's driver is not installed here.
    """
    import importlib
    import importlib.util

    location = _CONNECTORS.get(db_type)
    if location is None:
        _NOT_IMPLEMENTED.add(db_type)
        logger.warning("connector_not_implemented", db_type=db_type.value)
        return None

    module_name, class_name = location
    try:
        module = importlib.import_module(f"sandbox.connectors.{module_name}")
        connector_class = getattr(module, class_name)
        # Connectors that import their driver when they dial name it here.
        for driver in getattr(connector_class, "driver_modules", ()):
            if importlib.util.find_spec(driver) is None:
                raise ImportError(driver)
    except ImportError as e:
        logger.warning(
            "connector_driver_not_installed",
            db_type=db_type.value,
            missing=e.name or str(e),
        )
        return None
    except Exception as e:
        logger.error(
            "connector_load_failed",
            db_type=db_type.value,
            error=str(e),
        )
        return None

    register_connector(db_type, connector_class)
    return connector_class


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


# Database types this sandbox has no connector code for (as opposed to a
# connector whose driver package is not installed in this image).
_NOT_IMPLEMENTED: set[DatabaseType] = set()


def is_supported(db_type: str) -> bool:
    """
    Whether this sandbox has connector code for the database type at all.

    True also when the connector's driver is missing from this image — that is
    something an operator can install; a type without connector code can never
    connect, so a catalogue need not offer it.
    """
    from sandbox.core.config import normalize_db_type

    try:
        resolved = DatabaseType(normalize_db_type(db_type))
    except ValueError:
        return False
    if resolved in _CONNECTOR_REGISTRY:
        return True
    _load_connector(resolved)
    return resolved not in _NOT_IMPLEMENTED


def has_connector(db_type: str) -> bool:
    """
    Whether this sandbox can open connections of the given database type.

    Takes the name a client sends (aliases such as "postgres" or "sqlserver"
    included). False for a type the sandbox does not know and for a known type
    that has no connector here, so callers can say so before anything is
    stored or dialled.
    """
    from sandbox.core.config import normalize_db_type

    try:
        resolved = DatabaseType(normalize_db_type(db_type))
    except ValueError:
        return False
    return resolved in _CONNECTOR_REGISTRY or _load_connector(resolved) is not None


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
