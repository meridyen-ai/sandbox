"""MySQL database handler."""

from src.data_connectors.libs.constants import ConnectionArgType, HandlerType

# Handler metadata
name = "mysql"
type = HandlerType.DATA
title = "MySQL"
description = "Connect to MySQL and MariaDB databases"
version = "0.1.0"
icon_path = "mysql.svg"

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
        "default": 3306,
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
    "ssl": {
        "type": ConnectionArgType.BOOLEAN,
        "required": False,
        "label": "SSL",
        "description": "Enable SSL connection",
        "default": False,
    },
}

connection_args_example = {
    "host": "localhost",
    "port": 3306,
    "database": "mydb",
    "user": "root",
    "password": "password",
}

# Import handler class
try:
    from .mysql_handler import MySQLHandler as Handler
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
