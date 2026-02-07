"""SAP HANA handler."""

from src.data_connectors.libs.constants import ConnectionArgType, HandlerType

name = "sap_hana"
type = HandlerType.DATA
title = "SAP HANA"
description = "Connect to SAP HANA databases"
version = "0.1.0"
icon_path = "sap_hana.svg"

connection_args = {
    "host": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "Host",
        "description": "SAP HANA server hostname",
    },
    "port": {
        "type": ConnectionArgType.INTEGER,
        "required": True,
        "label": "Port",
        "description": "SAP HANA port (typically 3NN13 where NN is instance number)",
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
        "description": "Default schema",
    },
    "encrypt": {
        "type": ConnectionArgType.BOOLEAN,
        "required": False,
        "label": "Encrypt",
        "description": "Enable SSL encryption",
        "default": True,
    },
}

connection_args_example = {
    "host": "hana-server.example.com",
    "port": 30015,
    "user": "SYSTEM",
    "password": "password",
    "schema": "MYSCHEMA",
}

try:
    from .sap_hana_handler import SAPHanaHandler as Handler
    import_error = None
except Exception as e:
    Handler = None
    import_error = e

__all__ = ["Handler", "name", "type", "title", "description", "version", "connection_args", "connection_args_example", "import_error"]
