"""Amazon Athena handler."""

from src.data_connectors.libs.constants import ConnectionArgType, HandlerType

name = "athena"
type = HandlerType.DATA
title = "Amazon Athena"
description = "Connect to Amazon Athena serverless query service"
version = "0.1.0"
icon_path = "athena.svg"

connection_args = {
    "aws_access_key_id": {
        "type": ConnectionArgType.STRING,
        "required": False,
        "label": "AWS Access Key ID",
        "description": "AWS access key (uses default credentials if not provided)",
    },
    "aws_secret_access_key": {
        "type": ConnectionArgType.PASSWORD,
        "required": False,
        "secret": True,
        "label": "AWS Secret Access Key",
        "description": "AWS secret key",
    },
    "region_name": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "Region",
        "description": "AWS region (e.g., us-east-1)",
    },
    "s3_staging_dir": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "S3 Staging Directory",
        "description": "S3 path for query results (e.g., s3://bucket/path/)",
    },
    "database": {
        "type": ConnectionArgType.STRING,
        "required": False,
        "label": "Database",
        "description": "Default database (catalog)",
        "default": "default",
    },
    "workgroup": {
        "type": ConnectionArgType.STRING,
        "required": False,
        "label": "Workgroup",
        "description": "Athena workgroup",
        "default": "primary",
    },
}

connection_args_example = {
    "aws_access_key_id": "AKIAIOSFODNN7EXAMPLE",
    "aws_secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "region_name": "us-east-1",
    "s3_staging_dir": "s3://my-bucket/athena-results/",
    "database": "default",
}

try:
    from .athena_handler import AthenaHandler as Handler
    import_error = None
except Exception as e:
    Handler = None
    import_error = e

__all__ = ["Handler", "name", "type", "title", "description", "version", "connection_args", "connection_args_example", "import_error"]
