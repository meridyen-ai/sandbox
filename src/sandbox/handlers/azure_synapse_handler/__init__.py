"""Azure Synapse Analytics handler."""

from src.data_connectors.libs.constants import ConnectionArgType, HandlerType

name = "azure_synapse"
type = HandlerType.DATA
title = "Azure Synapse"
description = "Connect to Azure Synapse Analytics (formerly SQL Data Warehouse)"
version = "0.1.0"
icon_path = "azure_synapse.svg"

connection_args = {
    "host": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "Server",
        "description": "Azure Synapse server name (e.g., myserver.sql.azuresynapse.net)",
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
    "port": {
        "type": ConnectionArgType.INTEGER,
        "required": False,
        "label": "Port",
        "description": "Database port",
        "default": 1433,
    },
    "encrypt": {
        "type": ConnectionArgType.BOOLEAN,
        "required": False,
        "label": "Encrypt",
        "description": "Enable encryption",
        "default": True,
    },
}

connection_args_example = {
    "host": "myserver.sql.azuresynapse.net",
    "database": "mydb",
    "user": "admin",
    "password": "password",
}

try:
    from .azure_synapse_handler import AzureSynapseHandler as Handler
    import_error = None
except Exception as e:
    Handler = None
    import_error = e

__all__ = ["Handler", "name", "type", "title", "description", "version", "connection_args", "connection_args_example", "import_error"]
