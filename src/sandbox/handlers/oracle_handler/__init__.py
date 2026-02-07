"""Oracle database handler."""

from src.data_connectors.libs.constants import ConnectionArgType, HandlerType

name = "oracle"
type = HandlerType.DATA
title = "Oracle"
description = "Connect to Oracle databases"
version = "0.1.0"
icon_path = "oracle.svg"

connection_args = {
    "host": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "Host",
        "description": "Database server hostname",
    },
    "port": {
        "type": ConnectionArgType.INTEGER,
        "required": False,
        "label": "Port",
        "description": "Database port",
        "default": 1521,
    },
    "sid": {
        "type": ConnectionArgType.STRING,
        "required": False,
        "label": "SID",
        "description": "Oracle System ID (use SID or service_name)",
    },
    "service_name": {
        "type": ConnectionArgType.STRING,
        "required": False,
        "label": "Service Name",
        "description": "Oracle service name (use SID or service_name)",
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
    "dsn": {
        "type": ConnectionArgType.STRING,
        "required": False,
        "label": "DSN",
        "description": "Full DSN connection string (alternative to host/port/sid)",
    },
}

connection_args_example = {
    "host": "localhost",
    "port": 1521,
    "service_name": "ORCL",
    "user": "system",
    "password": "password",
}

try:
    from .oracle_handler import OracleHandler as Handler
    import_error = None
except Exception as e:
    Handler = None
    import_error = e

__all__ = ["Handler", "name", "type", "title", "description", "version", "connection_args", "connection_args_example", "import_error"]
