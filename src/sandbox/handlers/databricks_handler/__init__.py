"""Databricks handler."""

from src.data_connectors.libs.constants import ConnectionArgType, HandlerType

name = "databricks"
type = HandlerType.DATA
title = "Databricks"
description = "Connect to Databricks SQL warehouses and clusters"
version = "0.1.0"
icon_path = "databricks.svg"

connection_args = {
    "auth_type": {
        "type": ConnectionArgType.SELECT,
        "required": True,
        "label": "Authentication type",
        "description": "Choose authentication method",
        "default": "personal_access_token",
        "options": [
            {"value": "personal_access_token", "label": "Personal Access Token"},
            {"value": "service_account", "label": "Service Account"},
        ],
    },
    "host": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "Host",
        "description": "Databricks workspace hostname (e.g., adb-xxx.azuredatabricks.net)",
    },
    "http_path": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "HTTP Path",
        "description": "SQL warehouse or cluster HTTP path",
    },
    # Personal Access Token authentication
    "access_token": {
        "type": ConnectionArgType.PASSWORD,
        "required": True,
        "secret": True,
        "label": "Personal Access Token",
        "description": "Personal access token for authentication",
        "depends_on": {
            "field": "auth_type",
            "values": ["personal_access_token"],
        },
    },
    # Service Account (OAuth M2M) authentication
    "client_id": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "Client ID",
        "description": "Service principal client ID (Application ID)",
        "depends_on": {
            "field": "auth_type",
            "values": ["service_account"],
        },
    },
    "client_secret": {
        "type": ConnectionArgType.PASSWORD,
        "required": True,
        "secret": True,
        "label": "Client Secret",
        "description": "Service principal client secret",
        "depends_on": {
            "field": "auth_type",
            "values": ["service_account"],
        },
    },
    # Common optional fields
    "catalog": {
        "type": ConnectionArgType.STRING,
        "required": False,
        "label": "Catalog",
        "description": "Unity Catalog name",
        "default": "hive_metastore",
    },
    "schema": {
        "type": ConnectionArgType.STRING,
        "required": False,
        "label": "Schema",
        "description": "Default schema",
        "default": "default",
    },
}

connection_args_example = {
    "auth_type": "personal_access_token",
    "host": "adb-1234567890123456.7.azuredatabricks.net",
    "http_path": "/sql/1.0/warehouses/abcdef1234567890",
    "access_token": "dapi...",
    "catalog": "hive_metastore",
    "schema": "default",
}

try:
    from .databricks_handler import DatabricksHandler as Handler
    import_error = None
except Exception as e:
    Handler = None
    import_error = e

__all__ = ["Handler", "name", "type", "title", "description", "version", "connection_args", "connection_args_example", "import_error"]
