"""SQL Server database handler."""

from src.data_connectors.libs.constants import ConnectionArgType, HandlerType

name = "sqlserver"
type = HandlerType.DATA
title = "SQL Server"
description = "Connect to Microsoft SQL Server databases"
version = "0.1.0"
icon_path = "sqlserver.svg"

connection_args = {
    "host": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "Host",
        "description": "Database server hostname or IP address",
    },
    "port": {
        "type": ConnectionArgType.INTEGER,
        "required": False,
        "label": "Port",
        "description": "Database server port",
        "default": 1433,
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
    "encrypt": {
        "type": ConnectionArgType.BOOLEAN,
        "required": False,
        "label": "Encrypt",
        "description": "Enable encryption",
        "default": True,
    },
    "trust_server_certificate": {
        "type": ConnectionArgType.BOOLEAN,
        "required": False,
        "label": "Trust Server Certificate",
        "description": "Trust the server certificate without validation",
        "default": False,
    },
}

connection_args_example = {
    "host": "localhost",
    "port": 1433,
    "database": "mydb",
    "user": "sa",
    "password": "password",
}

try:
    from .sqlserver_handler import SQLServerHandler as Handler
    import_error = None
except Exception as e:
    Handler = None
    import_error = e

__all__ = ["Handler", "name", "type", "title", "description", "version", "connection_args", "connection_args_example", "import_error"]
