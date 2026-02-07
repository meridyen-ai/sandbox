"""PostgreSQL database handler."""

from src.data_connectors.libs.constants import ConnectionArgType, HandlerType

# Handler metadata
name = "postgres"
type = HandlerType.DATA
title = "PostgreSQL"
description = "Connect to PostgreSQL databases"
version = "0.1.0"
icon_path = "postgres.svg"

# Connection arguments
connection_args = {
    "host": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "Host",
        "description": "Database server hostname or IP address",
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
        "description": "SSL connection mode (disable, require, verify-ca, verify-full)",
        "default": "prefer",
    },
}

connection_args_example = {
    "host": "localhost",
    "port": 5432,
    "database": "mydb",
    "user": "postgres",
    "password": "password",
}

# Import handler class
try:
    from .postgres_handler import PostgresHandler as Handler
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
