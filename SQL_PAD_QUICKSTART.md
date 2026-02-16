# SQL Pad Quick Start Guide

## 🚀 What is SQL Pad?

SQL Pad is a modern web-based SQL query interface integrated into Meridyen Sandbox. It lets you:
- Browse database schemas visually
- Write and execute SQL queries with auto-complete
- View results in formatted tables
- Save and share queries
- Export data

## ⚡ Quick Start (3 minutes)

### 1. Start the services
```bash
cd meridyen-sandbox
docker compose -f docker-compose.hybrid.yaml -f docker-compose.dev.yaml up -d
```

### 2. Access the UI
Open your browser to: **http://localhost:5175**

### 3. Navigate to Query Explorer
Click **"Query Explorer"** in the top navigation menu

### 4. Start Querying!
- Select your database from the dropdown
- Write SQL in the editor
- Press `Ctrl+Enter` to execute

## 📍 Service Ports

| Service | Port | URL |
|---------|------|-----|
| Sandbox Frontend | 5175 | http://localhost:5175 |
| Sandbox Backend | 8081 | http://localhost:8081 |
| SQL Pad | 3010 | http://localhost:3010 |

## 🎨 UI Features (Best Practice UX)

### Modern Design
- ✅ Clean, intuitive interface
- ✅ Responsive layout (works on mobile)
- ✅ Dark mode support
- ✅ Smooth transitions and animations

### User-Friendly Features
- ✅ **Connection Selector** - Switch between databases easily
- ✅ **Fullscreen Mode** - Maximize your workspace
- ✅ **Quick Tips** - Helpful keyboard shortcuts
- ✅ **Error Handling** - Clear, actionable error messages
- ✅ **Loading States** - Never wonder if something's working

### Keyboard Shortcuts
| Shortcut | Action |
|----------|--------|
| `Ctrl+Enter` | Execute query |
| `Ctrl+S` | Save query |
| `Ctrl+/` | Comment line |
| `Ctrl+Space` | Auto-complete |

## 🔧 Configuration

### Default Credentials (Change in Production!)
- Email: `admin@meridyen.local`
- Password: `admin`

### Customize SQL Pad Settings

Edit `docker-compose.dev.yaml`:
```yaml
sqlpad:
  environment:
    - SQLPAD_ADMIN_PASSWORD=your-secure-password
    - SQLPAD_QUERY_RESULT_MAX_ROWS=100000
```

## 🎯 Common Use Cases

### 1. Explore Database Schema
- Click database name in sidebar
- Browse tables and columns
- Double-click to insert table name

### 2. Run Ad-hoc Queries
- Write query in editor
- Execute with `Ctrl+Enter`
- View results below

### 3. Save Queries for Reuse
- Click "Save Query"
- Give it a descriptive name
- Access from sidebar later

### 4. Share Query Results
- Run your query
- Click "Export" button
- Choose CSV or JSON format

## 🐛 Troubleshooting

### SQL Pad not loading?
```bash
# Check if container is running
docker ps | grep sqlpad

# View logs
docker logs meridyen-sqlpad

# Restart if needed
docker restart meridyen-sqlpad
```

### Can't see my database connection?
1. Verify connection in `config/sandbox.yaml`
2. Click refresh button in Query Explorer UI
3. Check sandbox backend logs:
   ```bash
   docker logs meridyen-sandbox-dev
   ```

### Query timeout?
Increase timeout in your connection config:
```yaml
resource_limits:
  max_cpu_seconds: 300
```

## 📚 Learn More

- **Full Documentation**: [docs/SQL_PAD_INTEGRATION.md](docs/SQL_PAD_INTEGRATION.md)
- **API Reference**: Check backend at http://localhost:8081/docs
- **SQL Pad Official Docs**: https://github.com/sqlpad/sqlpad

## 💡 Pro Tips

1. **Use Auto-complete** - Press `Ctrl+Space` while typing to see suggestions
2. **Save Frequently Used Queries** - Build your own query library
3. **Use Fullscreen** - Click maximize icon for better visibility
4. **Check Query History** - SQL Pad saves your last 50 queries

## 🎉 You're All Set!

Now you can:
- ✅ Browse your database schemas visually
- ✅ Run SQL queries with a modern editor
- ✅ Save and share queries with your team
- ✅ Export results for analysis

**Happy Querying! 🚀**
