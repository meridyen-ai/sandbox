# Testing SQL Pad Integration

## Quick Start

### 1. Restart Sandbox
```bash
cd /home/arash/projects/canovateai

# Stop current sandbox
make sandbox-down

# Start sandbox with new config
make sandbox-up
```

### 2. Access the UI
Open your browser to: http://localhost:5175

### 3. Login with API Key
Use this development API key:
```
sb_dev_test_key_123456789
```

### 4. Navigate to Query Explorer
Click "Query Explorer" in the top navigation

### 5. Start Querying!
- You should see "MVP PostgreSQL Database" in the dropdown
- Select it and start writing SQL queries
- Press `Ctrl+Enter` to execute

## Database Connection Details

The sandbox is now configured to connect to:
- **Host**: Your local PostgreSQL (via `host.docker.internal`)
- **Port**: 5432
- **Database**: `ai_assistants_dev`
- **Schema**: `public`

## Troubleshooting

### Error: "Failed to load database connections"

**Check if sandbox is running:**
```bash
docker ps | grep sandbox
```

**Check sandbox logs:**
```bash
make sandbox-logs
```

### Error: "Authentication required"

1. Make sure you're logged in with the API key
2. Check browser console (F12) for detailed errors
3. Verify the API key in localStorage:
   ```javascript
   // In browser console
   localStorage.getItem('sandbox_api_key')
   ```

### SQL Pad not loading

**Check if SQL Pad container is running:**
```bash
docker ps | grep sqlpad
```

**View SQL Pad logs:**
```bash
docker logs meridyen-sqlpad
```

**Restart SQL Pad:**
```bash
docker restart meridyen-sqlpad
```

### Connection timeout to PostgreSQL

**Verify PostgreSQL is accessible:**
```bash
# From host
psql -h localhost -p 5432 -U ai_assistants -d ai_assistants_dev

# Password: ai_assistants_password
```

If connection fails, check if PostgreSQL is running:
```bash
docker ps | grep postgres
```

## What's Configured

### config/sandbox.yaml

```yaml
database_connections:
  - id: "mvp_postgres"
    name: "MVP PostgreSQL Database"
    db_type: postgres
    host: "host.docker.internal"
    port: 5432
    database: "ai_assistants_dev"
    username: "ai_assistants"
    password: "ai_assistants_password"
    schema_name: "public"
```

### Authentication

```yaml
authentication:
  provider: static
  static_keys:
    - key: "sb_dev_test_key_123456789"
      workspace_id: "dev_workspace"
      name: "dev-key"
```

## Services Running

After `make sandbox-up`, you should have:

| Service | Port | URL |
|---------|------|-----|
| Sandbox Backend | 8081 | http://localhost:8081 |
| Sandbox API Docs | 8081 | http://localhost:8081/docs |
| Sandbox Frontend | 5175 | http://localhost:5175 |
| SQL Pad | 3010 | http://localhost:3010 |
| Metrics | 9091 | http://localhost:9091/metrics |

## Manual Testing

### Test 1: Backend Health Check
```bash
curl http://localhost:8081/health
```

Expected response:
```json
{
  "status": "healthy",
  "sandbox_id": "...",
  "version": "..."
}
```

### Test 2: List Connections (with auth)
```bash
curl -H "X-API-Key: sb_dev_test_key_123456789" \
  http://localhost:8081/api/v1/schema/full-sync
```

Should return connection info and tables.

### Test 3: SQL Pad Connection
```bash
curl -H "X-API-Key: sb_dev_test_key_123456789" \
  -X POST \
  "http://localhost:8081/api/v1/sqlpad/connection?connection_id=mvp_postgres"
```

Should return success.

### Test 4: Get SQL Pad Embed URL
```bash
curl -H "X-API-Key: sb_dev_test_key_123456789" \
  "http://localhost:8081/api/v1/sqlpad/embed-url?connection_id=mvp_postgres"
```

Should return an embed URL with token.

## Next Steps

Once everything is working:

1. ✅ Test queries in SQL Pad
2. ✅ Try fullscreen mode
3. ✅ Save a query
4. ✅ Test connection selector (add more databases)
5. ✅ Export query results

## Production Setup

For production, update these settings:

1. **Change API Keys**: Generate secure keys
2. **Use Environment Variables**: Don't hardcode credentials
3. **Enable SSL**: Add SSL certificates
4. **Use Remote Auth**: Connect to your auth provider
5. **Change SQL Pad Password**: Update SQLPAD_ADMIN_PASSWORD

See [docs/SQL_PAD_INTEGRATION.md](docs/SQL_PAD_INTEGRATION.md) for full docs.
