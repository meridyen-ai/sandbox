# SQL Pad Integration

## Overview

The Meridyen Sandbox now includes **SQL Pad** - a modern, web-based SQL query interface that allows users to explore their connected databases, run queries, and visualize results.

## Features

✅ **Multi-Database Support** - Works with PostgreSQL, MySQL, SQL Server, Snowflake, Redshift, and more
✅ **Modern Query Editor** - Syntax highlighting, auto-complete, and query history
✅ **Schema Browser** - Visual exploration of tables, columns, and relationships
✅ **Query Management** - Save and share queries across your team
✅ **Real-time Results** - Fast query execution with formatted result tables
✅ **Seamless Integration** - Automatically syncs with your sandbox connections

## Architecture

```
┌─────────────────────────────────────────┐
│   Frontend (React)                       │
│   ┌────────────────────────────────┐   │
│   │  DatabaseExplorer Component    │   │
│   │  - Connection Selector         │   │
│   │  - SQL Pad iframe             │   │
│   │  - Fullscreen mode            │   │
│   └────────────────────────────────┘   │
└──────────────┬──────────────────────────┘
               │ API Calls
┌──────────────▼──────────────────────────┐
│   Backend (FastAPI)                      │
│   ┌────────────────────────────────┐   │
│   │  /api/v1/sqlpad/*              │   │
│   │  - create_sqlpad_connection    │   │
│   │  - get_embed_url               │   │
│   │  - list_connections            │   │
│   └────────────┬───────────────────┘   │
└─────────────────┼───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│   SQL Pad Service (Docker)               │
│   - Port: 3010                          │
│   - Web-based query interface           │
│   - Connection management               │
│   - Query history & saved queries       │
└─────────────────────────────────────────┘
```

## Getting Started

### 1. Start Services

```bash
# From the meridyen-sandbox directory
docker compose -f docker-compose.hybrid.yaml -f docker-compose.dev.yaml up

# Or use the Makefile (if available)
make dev-full
```

This will start:
- **Sandbox Backend** on port 8081
- **Sandbox Frontend** on port 5175
- **SQL Pad** on port 3010

### 2. Access SQL Pad

#### Via Integrated UI (Recommended)
1. Open the Sandbox Frontend: http://localhost:5175
2. Login with your credentials
3. Click **"Query Explorer"** in the navigation menu
4. Select a database connection from the dropdown
5. Start querying!

#### Direct Access
- SQL Pad UI: http://localhost:3010
- Default credentials: `admin@meridyen.local` / `admin`

### 3. Connect Your Database

SQL Pad connections are automatically synced from your sandbox configuration:

1. Add a database connection in `config/sandbox.yaml`:
   ```yaml
   database_connections:
     - id: my_postgres
       name: "My PostgreSQL Database"
       db_type: postgres
       host: db.example.com
       port: 5432
       database: my_database
       username: my_user
       password: my_password
       schema_name: public
   ```

2. The connection will automatically appear in SQL Pad when you access the Query Explorer

## API Endpoints

### Create/Update SQL Pad Connection
```http
POST /api/v1/sqlpad/connection?connection_id=my_connection
Authorization: Bearer <your-token>

Response:
{
  "status": "success",
  "data": {
    "connection_id": "my_connection",
    "name": "My Database",
    "driver": "postgres"
  }
}
```

### Get Embed URL
```http
GET /api/v1/sqlpad/embed-url?connection_id=my_connection
Authorization: Bearer <your-token>

Response:
{
  "status": "success",
  "data": {
    "embed_url": "http://sqlpad:3000/?access_token=xxx&connectionId=my_connection"
  }
}
```

### List Connections
```http
GET /api/v1/sqlpad/connections
Authorization: Bearer <your-token>

Response:
{
  "status": "success",
  "data": [
    {
      "id": "my_connection",
      "name": "My Database",
      "driver": "postgres"
    }
  ]
}
```

## Usage Guide

### Running Queries

1. **Select Connection**: Choose your database from the dropdown
2. **Write Query**: Use the SQL editor with syntax highlighting
3. **Execute**: Press `Ctrl+Enter` or click the "Run" button
4. **View Results**: Results appear in a formatted table below

### Keyboard Shortcuts

- `Ctrl+Enter` - Execute query
- `Ctrl+S` - Save query
- `Ctrl+/` - Toggle comment
- `Ctrl+Space` - Auto-complete

### Schema Browser

- Click on database name to expand tables
- Click on table name to see columns and types
- Double-click table name to insert into query

### Saving Queries

1. Write your query
2. Click "Save Query" button
3. Give it a name and optional description
4. Access saved queries from the sidebar

## Configuration

### Environment Variables

SQL Pad can be configured via environment variables in `docker-compose.dev.yaml`:

```yaml
environment:
  # Admin credentials
  - SQLPAD_ADMIN=admin@meridyen.local
  - SQLPAD_ADMIN_PASSWORD=admin

  # Query limits
  - SQLPAD_QUERY_RESULT_MAX_ROWS=100000

  # Session configuration
  - SQLPAD_SESSION_SECRET=change-me-in-production

  # Public URL (for embedding)
  - SQLPAD_PUBLIC_URL=http://localhost:3010
```

### Frontend Configuration

Configure the API endpoint in your frontend `.env` file:

```bash
VITE_API_URL=http://localhost:8081
```

## Best Practices

### Security

1. **Change Default Password**: Update `SQLPAD_ADMIN_PASSWORD` in production
2. **Use HTTPS**: Configure SSL certificates for production deployment
3. **API Key Auth**: Frontend uses API keys for sandbox authentication
4. **Network Isolation**: SQL Pad runs in isolated Docker network

### Performance

1. **Query Limits**: Default max rows is 100,000 (configurable)
2. **Connection Pooling**: Connections are reused for efficiency
3. **Timeout**: Queries timeout after 60 seconds (configurable)

### User Experience

1. **Connection Selector**: Easy switching between multiple databases
2. **Fullscreen Mode**: Maximize screen space for complex queries
3. **Quick Tips**: Helpful keyboard shortcuts displayed on first use
4. **Error Messages**: Clear feedback when queries fail

## Troubleshooting

### SQL Pad Not Loading

**Problem**: White screen or connection error

**Solution**:
```bash
# Check if SQL Pad is running
docker ps | grep sqlpad

# Check SQL Pad logs
docker logs meridyen-sqlpad

# Restart SQL Pad
docker restart meridyen-sqlpad
```

### Authentication Error

**Problem**: "Failed to authenticate with SQL Pad"

**Solution**:
1. Check environment variables are set correctly
2. Verify SQL Pad credentials in `docker-compose.dev.yaml`
3. Check sandbox backend logs:
   ```bash
   docker logs meridyen-sandbox-dev
   ```

### Connection Not Appearing

**Problem**: Database connection not showing in SQL Pad

**Solution**:
1. Verify connection exists in `config/sandbox.yaml`
2. Click refresh button in Query Explorer
3. Check backend API endpoint:
   ```bash
   curl -H "X-API-Key: your-key" \
     http://localhost:8081/api/v1/sqlpad/connections
   ```

### Query Timeout

**Problem**: Long-running queries timeout

**Solution**:
Increase timeout in sandbox configuration:
```yaml
resource_limits:
  max_cpu_seconds: 300  # 5 minutes
```

## Advanced Features

### Custom SQL Pad Configuration

Mount a custom configuration file:

```yaml
# docker-compose.dev.yaml
volumes:
  - ./config/sqlpad-config.ini:/etc/sqlpad/sqlpad.ini:ro
```

### Multi-User Setup

SQL Pad supports multiple users:

1. Access SQL Pad admin panel: http://localhost:3010/admin
2. Create user accounts
3. Assign connection permissions
4. Configure role-based access

### Query Sharing

Share queries with your team:

1. Save query with descriptive name
2. Copy query URL
3. Share with team members
4. They can view and execute the query

## Production Deployment

### Security Checklist

- [ ] Change default admin password
- [ ] Enable HTTPS with valid SSL certificate
- [ ] Configure firewall rules (restrict port 3010)
- [ ] Use secrets management for credentials
- [ ] Enable audit logging
- [ ] Set up regular backups

### Scaling

For high-traffic deployments:

1. **Load Balancing**: Run multiple SQL Pad instances
2. **Connection Pooling**: Configure max connections
3. **Resource Limits**: Set memory/CPU limits
4. **Caching**: Enable query result caching

## Support

For issues or feature requests:

1. Check logs: `docker logs meridyen-sqlpad`
2. Review SQL Pad docs: https://github.com/sqlpad/sqlpad
3. Contact Meridyen support

## What's Next?

Planned enhancements:
- [ ] Query result export (CSV, JSON)
- [ ] Collaborative editing
- [ ] Query scheduling
- [ ] Advanced visualizations
- [ ] Custom themes
