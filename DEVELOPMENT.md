# Development Guide

## Quick Start

### Development with Hot Reload (Recommended - Docker Compose)

The easiest way to develop is using `make dev-full` which uses Docker Compose with volume mounts for hot reloading:

```bash
make dev-full
```

This will start:
- **Backend (Uvicorn)** on http://localhost:8080 with auto-reload
- **Frontend (Vite)** on http://localhost:5173 with hot module replacement (HMR)

**Features:**
- ✅ Hot reload for both backend and frontend
- ✅ Code changes reflected immediately
- ✅ Isolated environment with Docker
- ✅ No need to install dependencies locally
- ✅ Source code mounted as volumes

Press `Ctrl+C` to stop all services.

**How it works:**
- Uses `docker-compose.hybrid.yaml` as base
- Overlays `docker-compose.dev.yaml` for development config
- Mounts `./src` and `./frontend` as volumes
- Backend runs with `uvicorn --reload`
- Frontend runs with `npm run dev` (Vite HMR)

### Background Development Mode

Run services in background (detached mode):

```bash
make dev-full-detached   # Start in background
make dev-logs            # View logs
make dev-stop            # Stop services
make dev-restart         # Restart services
```

### Local Development (No Docker)

If you prefer to run without Docker:

```bash
# First, install dependencies
make install     # Python dependencies
make install-ui  # Frontend dependencies

# Then run in local mode
make dev-local
```

Or run services separately:

```bash
# Terminal 1: Backend with hot reload
make dev-backend

# Terminal 2: Frontend with hot reload
make dev-ui
```

## What Gets Hot Reloaded?

### Backend (Uvicorn --reload)
- ✅ Python source files (`.py`)
- ✅ API endpoint changes
- ✅ Business logic updates
- ✅ Handler implementations
- ❌ Configuration files (requires restart)
- ❌ Proto files (run `make proto` then restart)
- **Reload time:** ~1-2 seconds

### Frontend (Vite HMR)
- ✅ React components (`.tsx`, `.jsx`)
- ✅ TypeScript files (`.ts`)
- ✅ CSS/SCSS files
- ✅ State management code
- ✅ API utils
- ⚡ Near-instant updates (<100ms)
- ⚡ Preserves React component state

## Development Workflow

### 1. Making Backend Changes

```bash
# Start dev environment
make dev-full

# In another terminal, edit Python files
vim src/sandbox/services/rest_api.py

# Watch the backend container logs - it will restart automatically
# Changes are live in ~1-2 seconds
```

**Example: Adding a new API endpoint**

```python
# src/sandbox/services/rest_api.py

@app.get("/api/v1/my-new-endpoint")
async def my_new_endpoint():
    return {"message": "Hello from new endpoint"}
```

Save the file → Backend restarts → Endpoint available at http://localhost:8080/api/v1/my-new-endpoint

### 2. Making Frontend Changes

```bash
# Start dev environment
make dev-full

# Edit React components
vim frontend/src/components/connections/ConnectionsPage.tsx

# Browser automatically updates within milliseconds
# No page refresh - state is preserved
```

**Example: Updating a component**

```tsx
// frontend/src/components/connections/ConnectionsPage.tsx

export function ConnectionsPage() {
  return (
    <div>
      <h1>My Updated Title</h1>
      {/* Your changes appear instantly */}
    </div>
  )
}
```

Save the file → Vite HMR → Browser updates instantly

### 3. Testing API Changes

```bash
# Backend running on http://localhost:8080

# Test with curl
curl http://localhost:8080/api/v1/handlers

# Or visit the interactive API docs
open http://localhost:8080/docs

# Or use the frontend
open http://localhost:5173
```

### 4. Viewing Logs

```bash
# All logs
make dev-logs

# Just backend logs
docker compose -f docker-compose.hybrid.yaml -f docker-compose.dev.yaml logs -f sandbox

# Just frontend logs
docker compose -f docker-compose.hybrid.yaml -f docker-compose.dev.yaml logs -f frontend
```

## Common Development Tasks

### Run Tests

```bash
make test              # Run all tests
make test-quick        # Run tests with early exit on failure
```

### Lint and Format Code

```bash
make lint              # Check code style
make format            # Auto-format code
```

### Generate gRPC Code

```bash
make proto             # Regenerate proto files
make dev-restart       # Restart to pick up changes
```

### Rebuild Containers

```bash
# Rebuild and restart (useful after dependency changes)
docker compose -f docker-compose.hybrid.yaml -f docker-compose.dev.yaml up --build
```

## Docker Compose Configuration

### Files

- **docker-compose.hybrid.yaml**: Base configuration for hybrid mode
- **docker-compose.dev.yaml**: Development overrides with hot reload

### Development Overrides (`docker-compose.dev.yaml`)

```yaml
services:
  sandbox:
    # Mounts source code as volume
    volumes:
      - ./src:/app/src:rw

    # Runs with uvicorn --reload
    command: uvicorn sandbox.main:app --reload

    # Development environment
    environment:
      - SANDBOX_ENVIRONMENT=development
      - SANDBOX_DEBUG=true

  frontend:
    # Mounts frontend code as volume
    volumes:
      - ./frontend:/app:rw

    # Runs Vite dev server
    command: npm run dev
```

### Volume Mounts

The dev configuration mounts your local source code:
- `./src` → `/app/src` (backend)
- `./frontend` → `/app` (frontend)

Changes to files in these directories are immediately visible to the containers.

## Architecture

### Backend Stack
- **FastAPI**: REST API framework
- **Uvicorn**: ASGI server with auto-reload
- **gRPC**: High-performance RPC
- **Pydantic**: Data validation and settings
- **PostgreSQL/MySQL**: Database connectors

### Frontend Stack
- **React 18**: UI framework
- **TypeScript**: Type-safe JavaScript
- **Vite**: Build tool with HMR
- **TanStack Query**: Server state management
- **Tailwind CSS**: Utility-first CSS

### Hot Reload Technology

**Backend (Uvicorn --reload):**
- Watches Python files for changes
- Gracefully restarts worker process
- Preserves connections where possible
- ~1-2 second restart time

**Frontend (Vite HMR):**
- Uses native ES modules
- Hot Module Replacement via WebSocket
- Preserves React component state
- <100ms update time

## Troubleshooting

### Backend not auto-reloading?

```bash
# Check if volumes are mounted correctly
docker compose -f docker-compose.hybrid.yaml -f docker-compose.dev.yaml ps

# Check backend logs for errors
make dev-logs

# Restart containers
make dev-restart
```

### Frontend not hot reloading?

```bash
# Check frontend logs
docker compose -f docker-compose.hybrid.yaml -f docker-compose.dev.yaml logs frontend

# Rebuild frontend container
docker compose -f docker-compose.hybrid.yaml -f docker-compose.dev.yaml up --build frontend
```

### Port conflicts?

```bash
# Check what's running on ports
lsof -i :8080  # Backend
lsof -i :5173  # Frontend

# Stop conflicting services
make dev-stop

# Or kill processes
kill -9 <PID>
```

### Changes not appearing?

1. **Check file saved**: Ensure your editor saved the file
2. **Check logs**: Look for errors in `make dev-logs`
3. **Check volumes**: Verify volumes mounted with `docker inspect`
4. **Hard refresh**: Browser cache (Cmd+Shift+R / Ctrl+Shift+F5)
5. **Restart**: `make dev-restart`

### Dependencies changed?

```bash
# Backend dependencies (pyproject.toml)
make dev-stop
docker compose -f docker-compose.hybrid.yaml -f docker-compose.dev.yaml up --build

# Frontend dependencies (package.json)
docker compose -f docker-compose.hybrid.yaml -f docker-compose.dev.yaml exec frontend npm install
```

## Production Build

```bash
# Build frontend for production
make build-ui

# Build Docker images
make build

# Run in production mode
make run-with-ui
```

## Environment Variables

### Backend
Configure via `config/sandbox.yaml` or environment variables:
- `SANDBOX_ENVIRONMENT`: development/production
- `SANDBOX_DEBUG`: true/false
- `SANDBOX_REST_PORT`: REST API port (default: 8080)

### Frontend
Configure via Vite:
- Proxy to backend automatically configured in `vite.config.ts`
- API calls to `/api/*` forwarded to `http://localhost:8080`

## Best Practices

### Backend Development
1. Use type hints for better IDE support
2. Add docstrings to public functions
3. Use structured logging (`logger.info("event", key=value)`)
4. Write tests for new endpoints
5. Check logs after save to confirm restart

### Frontend Development
1. Use TypeScript strict mode
2. Define types for API responses
3. Use React Query for API calls
4. Keep components small and focused
5. Watch browser console for errors

### Hot Reload Tips
1. **Small changes** work best - commit often
2. **Watch logs** for reload confirmations
3. **Backend restarts** may interrupt active requests
4. **Frontend HMR** preserves most component state
5. **Hard refresh** if something seems cached

## Performance Tips

### Faster Backend Restarts
- Keep imports minimal
- Lazy load heavy dependencies
- Use FastAPI dependency injection

### Faster Frontend Updates
- Use named exports
- Avoid default exports
- Keep component tree shallow
- Use React.memo strategically

## Additional Resources

- FastAPI docs: https://fastapi.tiangolo.com/
- Vite docs: https://vitejs.dev/
- TanStack Query: https://tanstack.com/query/latest
- Uvicorn: https://www.uvicorn.org/
- Docker Compose: https://docs.docker.com/compose/
