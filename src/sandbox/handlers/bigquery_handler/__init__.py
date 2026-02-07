"""Google BigQuery handler."""

from src.data_connectors.libs.constants import ConnectionArgType, HandlerType

name = "bigquery"
type = HandlerType.DATA
title = "Google BigQuery"
description = "Connect to Google BigQuery data warehouse"
version = "0.1.0"
icon_path = "bigquery.svg"

connection_args = {
    "project_id": {
        "type": ConnectionArgType.STRING,
        "required": True,
        "label": "Project ID",
        "description": "Google Cloud project ID",
    },
    "dataset": {
        "type": ConnectionArgType.STRING,
        "required": False,
        "label": "Dataset",
        "description": "Default dataset name",
    },
    "credentials_json": {
        "type": ConnectionArgType.DICT,
        "required": False,
        "secret": True,
        "label": "Service Account JSON",
        "description": "Service account credentials as JSON object",
    },
    "credentials_file": {
        "type": ConnectionArgType.PATH,
        "required": False,
        "label": "Credentials File",
        "description": "Path to service account JSON file",
    },
    "location": {
        "type": ConnectionArgType.STRING,
        "required": False,
        "label": "Location",
        "description": "BigQuery location (e.g., US, EU)",
        "default": "US",
    },
}

connection_args_example = {
    "project_id": "my-project-id",
    "dataset": "my_dataset",
    "credentials_file": "/path/to/service-account.json",
}

try:
    from .bigquery_handler import BigQueryHandler as Handler
    import_error = None
except Exception as e:
    Handler = None
    import_error = e

__all__ = ["Handler", "name", "type", "title", "description", "version", "connection_args", "connection_args_example", "import_error"]
