"""Amazon Aurora PostgreSQL database handler."""

from src.data_connectors.libs.constants import ConnectionArgType, HandlerType

# Handler metadata
name = "aurora_postgres"
type = HandlerType.DATA
title = "Amazon Aurora PostgreSQL"
description = "Connect to Amazon Aurora PostgreSQL-compatible databases"
version = "0.1.0"
icon_path = "aurora_postgres.svg"

# Connection arguments
connection_args = {
    "host": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "Host",
        "description": "Aurora cluster endpoint (e.g., mycluster.cluster-xxxxx.us-east-1.rds.amazonaws.com)",
    },
    "port": {
        "type": ConnectionArgType.INTEGER,
        "required": True,
        "label": "Port",
        "description": "Database server port",
        "default": 5432,
    },
    "database": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "Database",
        "description": "Database name",
    },
    "user": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "User",
        "description": "Database username",
    },
    "password": {
        "type": ConnectionArgType.PASSWORD,
        "required": True,
        "secret": True,
        "label": "Password",
        "description": "Database password",
    },
    "schema": {
        "type": ConnectionArgType.STRING,
        "required": False,
        "label": "Schema",
        "description": "Default schema (defaults to 'public')",
        "default": "public",
    },
    "sslmode": {
        "type": ConnectionArgType.STRING,
        "required": False,
        "label": "SSL Mode",
        "description": "SSL connection mode (disable, require, verify-ca, verify-full). Recommended: require or verify-full for Aurora",
        "default": "require",
    },
    "sslrootcert": {
        "type": ConnectionArgType.STRING,
        "required": False,
        "label": "SSL Root Certificate",
        "description": "Path to AWS RDS CA certificate bundle",
    },
}

connection_args_example = {
    "host": "mycluster.cluster-xxxxx.us-east-1.rds.amazonaws.com",
    "port": 5432,
    "database": "mydb",
    "user": "postgres",
    "password": "password",
    "sslmode": "require",
}

# Import handler class
try:
    from .aurora_postgres_handler import AuroraPostgresHandler as Handler
    import_error = None
except Exception as e:
    Handler = None
    import_error = e

__all__ = [
    "Handler",
    "name",
    "type",
    "title",
    "description",
    "version",
    "connection_args",
    "connection_args_example",
    "import_error",
]
