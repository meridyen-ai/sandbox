# @meridyen/sandbox-client

TypeScript/JavaScript client for the [Meridyen Sandbox](https://github.com/meridyen-ai/sandbox) execution engine.

## Installation

```bash
npm install @meridyen/sandbox-client
```

## Quick Start

```typescript
import { SandboxClient } from '@meridyen/sandbox-client'

const client = new SandboxClient({
  baseUrl: 'http://localhost:8080',
  apiKey: 'sb_your-api-key',
})

// Execute SQL
const result = await client.executeSQL({
  context: { connection_id: 'my-postgres' },
  query: 'SELECT * FROM users LIMIT 10',
})
console.log(result.columns, result.rows)

// Execute Python
const pyResult = await client.executePython({
  context: {},
  code: 'import pandas as pd\nprint(pd.DataFrame(INPUT_DATA).describe())',
  input_data: { data: [{ x: 1 }, { x: 2 }, { x: 3 }] },
})
console.log(pyResult.stdout)

// Health check
const health = await client.health()
console.log(health.status, health.version)
```

## API

### `new SandboxClient(config)`

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `baseUrl` | `string` | (required) | Sandbox REST API URL |
| `apiKey` | `string` | `''` | API key (`sb_xxx`) |
| `timeout` | `number` | `30000` | Request timeout (ms) |
| `headers` | `Record<string, string>` | `{}` | Extra headers |

### Execution

- `executeSQL(request)` — Execute SQL query
- `executePython(request)` — Execute Python code in sandbox
- `createVisualization(request)` — Generate Plotly chart

### Connections

- `listConnections()` — List database connections
- `createConnection(config)` — Create connection
- `updateConnection(id, config)` — Update connection
- `deleteConnection(id)` — Delete connection
- `testConnection(config)` — Test connection

### Schema

- `syncSchema(connectionId, options?)` — Get schema metadata
- `fullSync(options?)` — Bulk sync all connections
- `getTableSamples(connectionId, tableName, limit?)` — Get sample rows

### Health

- `health()` — Health check
- `capabilities()` — Sandbox capabilities and limits
- `listHandlers()` — Available database handlers

## Requirements

- Node.js 18+ (uses native `fetch`)
- No runtime dependencies

## License

Apache-2.0
