"""Trino (and Presto) handler."""

from src.data_connectors.libs.constants import ConnectionArgType, HandlerType

name = "trino"
type = HandlerType.DATA
title = "Trino"
description = "Connect to Trino (formerly PrestoSQL) and Presto query engines"
version = "0.1.0"
icon_path = "trino.svg"

connection_args = {
    "host": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "Host",
        "description": "Trino coordinator hostname",
    },
    "port": {
        "type": ConnectionArgType.INTEGER,
        "required": False,
        "label": "Port",
        "description": "Trino port",
        "default": 8080,
    },
    "user": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "User",
        "description": "Username for authentication",
    },
    "password": {
        "type": ConnectionArgType.PASSWORD,
        "required": False,
        "secret": True,
        "label": "Password",
        "description": "Password (if authentication enabled)",
    },
    "catalog": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "Catalog",
        "description": "Default catalog name",
    },
    "schema": {
        "type": ConnectionArgType.STRING,
        "required": False,
        "label": "Schema",
        "description": "Default schema name",
    },
    "http_scheme": {
        "type": ConnectionArgType.STRING,
        "required": False,
        "label": "HTTP Scheme",
        "description": "Connection scheme (http or https)",
        "default": "http",
    },
}

connection_args_example = {
    "host": "localhost",
    "port": 8080,
    "user": "admin",
    "catalog": "hive",
    "schema": "default",
}

try:
    from .trino_handler import TrinoHandler as Handler
    import_error = None
except Exception as e:
    Handler = None
    import_error = e

__all__ = ["Handler", "name", "type", "title", "description", "version", "connection_args", "connection_args_example", "import_error"]
