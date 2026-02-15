# meridyen-sandbox-client

Python client for the [Meridyen Sandbox](https://github.com/meridyen-ai/sandbox) execution engine.

## Installation

```bash
pip install meridyen-sandbox-client
```

## Quick Start

```python
import asyncio
from meridyen_sandbox_client import SandboxClient

async def main():
    async with SandboxClient("http://localhost:8080", api_key="sb_your-key") as client:
        # Health check
        health = await client.health()
        print(f"Sandbox: {health.status} (v{health.version})")

        # Execute SQL
        result = await client.execute_sql(
            query="SELECT * FROM users LIMIT 10",
            connection_id="my-postgres",
        )
        print(f"Got {result.row_count} rows")
        for row in result.rows:
            print(row)

        # Execute Python
        py_result = await client.execute_python(
            code="import pandas as pd\ndf = pd.DataFrame(INPUT_DATA)\nprint(df.describe())",
            input_data={"data": [{"x": 1}, {"x": 2}, {"x": 3}]},
        )
        print(py_result.stdout)

asyncio.run(main())
```

## API

### `SandboxClient(base_url, api_key=None, timeout=60.0)`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `base_url` | `str` | (required) | Sandbox REST API URL |
| `api_key` | `str` | `None` | API key (`sb_xxx`) |
| `timeout` | `float` | `60.0` | Request timeout (seconds) |
| `headers` | `dict` | `None` | Extra headers |

### Execution

- `execute_sql(query, connection_id, parameters=None)` — Execute SQL
- `execute_python(code, input_data=None, variables=None)` — Execute Python
- `create_visualization(data, instruction, chart_type="auto")` — Generate chart

### Connections

- `list_connections()` — List database connections
- `create_connection(config)` — Create connection
- `delete_connection(id)` — Delete connection
- `test_connection(config)` — Test connection

### Schema

- `sync_schema(connection_id, include_samples=True)` — Get schema metadata
- `get_table_samples(connection_id, table_name, limit=10)` — Get sample rows

### Health

- `health()` — Health check
- `health_check()` — Returns `True` if healthy
- `capabilities()` — Sandbox capabilities

## Requirements

- Python 3.10+
- `httpx` (only dependency)

## License

Apache-2.0
