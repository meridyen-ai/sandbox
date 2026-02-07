"""Amazon Redshift handler."""

from src.data_connectors.libs.constants import ConnectionArgType, HandlerType

name = "redshift"
type = HandlerType.DATA
title = "Amazon Redshift"
description = "Connect to Amazon Redshift data warehouse"
version = "0.1.0"
icon_path = "redshift.svg"

connection_args = {
    "auth_type": {
        "type": ConnectionArgType.SELECT,
        "required": True,
        "label": "Authentication type",
        "description": "Choose authentication method",
        "default": "service_account",
        "options": [
            {"value": "service_account", "label": "Service Account"},
            {"value": "iam", "label": "IAM"},
        ],
    },
    "host": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "Host",
        "description": "Redshift cluster endpoint",
    },
    "port": {
        "type": ConnectionArgType.INTEGER,
        "required": False,
        "label": "Port",
        "description": "Database port",
        "default": 5439,
    },
    "database": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "Database",
        "description": "Database name",
    },
    # Service Account authentication fields
    "user": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "User",
        "description": "Database username",
        "depends_on": {
            "field": "auth_type",
            "values": ["service_account"],
        },
    },
    "password": {
        "type": ConnectionArgType.PASSWORD,
        "required": True,
        "secret": True,
        "label": "Password",
        "description": "Database password",
        "depends_on": {
            "field": "auth_type",
            "values": ["service_account"],
        },
    },
    # IAM authentication fields
    "aws_access_key_id": {
        "type": ConnectionArgType.STRING,
        "required": False,
        "label": "AWS Access Key ID",
        "description": "AWS access key (uses default credentials if not provided)",
        "depends_on": {
            "field": "auth_type",
            "values": ["iam"],
        },
    },
    "aws_secret_access_key": {
        "type": ConnectionArgType.PASSWORD,
        "required": False,
        "secret": True,
        "label": "AWS Secret Access Key",
        "description": "AWS secret key",
        "depends_on": {
            "field": "auth_type",
            "values": ["iam"],
        },
    },
    "db_user": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "Database User",
        "description": "Database user for IAM authentication",
        "depends_on": {
            "field": "auth_type",
            "values": ["iam"],
        },
    },
    "cluster_identifier": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "Cluster Identifier",
        "description": "Redshift cluster identifier (e.g., my-cluster)",
        "depends_on": {
            "field": "auth_type",
            "values": ["iam"],
        },
    },
    "region": {
        "type": ConnectionArgType.STRING,
        "required": False,
        "label": "AWS Region",
        "description": "AWS region (e.g., us-east-1). Extracted from host if not provided.",
        "depends_on": {
            "field": "auth_type",
            "values": ["iam"],
        },
    },
    # Common optional fields
    "schema": {
        "type": ConnectionArgType.STRING,
        "required": False,
        "label": "Schema",
        "description": "Default schema",
        "default": "public",
    },
    "sslmode": {
        "type": ConnectionArgType.STRING,
        "required": False,
        "label": "SSL Mode",
        "description": "SSL connection mode",
        "default": "require",
    },
}

connection_args_example = {
    "auth_type": "service_account",
    "host": "my-cluster.xxxx.us-east-1.redshift.amazonaws.com",
    "port": 5439,
    "database": "dev",
    "user": "admin",
    "password": "password",
}

try:
    from .redshift_handler import RedshiftHandler as Handler
    import_error = None
except Exception as e:
    Handler = None
    import_error = e

__all__ = ["Handler", "name", "type", "title", "description", "version", "connection_args", "connection_args_example", "import_error"]
