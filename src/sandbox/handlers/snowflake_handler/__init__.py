"""Snowflake data warehouse handler."""

from src.data_connectors.libs.constants import ConnectionArgType, HandlerType

name = "snowflake"
type = HandlerType.DATA
title = "Snowflake"
description = "Connect to Snowflake data warehouse"
version = "0.1.0"
icon_path = "snowflake.svg"

connection_args = {
    "account": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "Account",
        "description": "Snowflake account identifier (e.g., xy12345.us-east-1)",
    },
    "user": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "User",
        "description": "Snowflake username",
    },
    "password": {
        "type": ConnectionArgType.PASSWORD,
        "required": True,
        "secret": True,
        "label": "Password",
        "description": "Snowflake password",
    },
    "database": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "Database",
        "description": "Database name",
    },
    "warehouse": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "Warehouse",
        "description": "Compute warehouse name",
    },
    "schema": {
        "type": ConnectionArgType.STRING,
        "required": False,
        "label": "Schema",
        "description": "Schema name",
        "default": "PUBLIC",
    },
    "role": {
        "type": ConnectionArgType.STRING,
        "required": False,
        "label": "Role",
        "description": "Snowflake role",
    },
}

connection_args_example = {
    "account": "xy12345.us-east-1",
    "user": "myuser",
    "password": "password",
    "database": "MYDB",
    "warehouse": "COMPUTE_WH",
    "schema": "PUBLIC",
}

try:
    from .snowflake_handler import SnowflakeHandler as Handler
    import_error = None
except Exception as e:
    Handler = None
    import_error = e

__all__ = ["Handler", "name", "type", "title", "description", "version", "connection_args", "connection_args_example", "import_error"]
