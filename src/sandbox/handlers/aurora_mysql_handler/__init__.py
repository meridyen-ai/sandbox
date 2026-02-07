"""Amazon Aurora MySQL database handler."""

from src.data_connectors.libs.constants import ConnectionArgType, HandlerType

# Handler metadata
name = "aurora_mysql"
type = HandlerType.DATA
title = "Amazon Aurora MySQL"
description = "Connect to Amazon Aurora MySQL-compatible databases"
version = "0.1.0"
icon_path = "aurora_mysql.svg"

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
        "description": "Enable SSL connection (recommended for Aurora)",
        "default": True,
    },
    "ssl_ca": {
        "type": ConnectionArgType.STRING,
        "required": False,
        "label": "SSL CA Certificate Path",
        "description": "Path to AWS RDS CA certificate bundle",
    },
}

connection_args_example = {
    "host": "mycluster.cluster-xxxxx.us-east-1.rds.amazonaws.com",
    "port": 3306,
    "database": "mydb",
    "user": "admin",
    "password": "password",
    "ssl": True,
}

# Import handler class
try:
    from .aurora_mysql_handler import AuroraMySQLHandler as Handler
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
