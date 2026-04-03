# =============================================================================
# Meridyen Sandbox Makefile
# =============================================================================

.PHONY: help build build-airgapped run run-airgapped stop dev test lint format clean sandbox sandbox-dev sandbox-stop rebuild-sandbox rebuild-sandbox-full

# Stack file: hybrid (API + postgres) or standalone (API + postgres + frontend container)
SANDBOX_COMPOSE ?= docker-compose.hybrid.yaml

# Default target
help:
	@echo "Meridyen Sandbox - Available Commands"
	@echo "======================================"
	@echo ""
	@echo "Build Commands:"
	@echo "  make build           - Build standard sandbox image"
	@echo "  make build-airgapped - Build air-gapped sandbox image (with local LLM)"
	@echo "  make build-ui        - Build frontend UI"
	@echo "  make push            - Push images to Docker Hub"
	@echo ""
	@echo "Run Commands:"
	@echo "  make run             - Run sandbox in hybrid mode"
	@echo "  make run-airgapped   - Run sandbox in air-gapped mode"
	@echo "  make run-with-ui     - Run sandbox with web UI"
	@echo "  make stop            - Stop all sandbox containers"
	@echo "  make logs            - View sandbox logs"
	@echo ""
	@echo "Development Commands:"
	@echo "  make dev-full        - Run backend + UI with hot reload (Docker)"
	@echo "  make dev-full-detached - Same but in background"
	@echo "  make dev-local       - Run backend + UI locally (no Docker)"
	@echo "  make dev-backend     - Run backend only with hot reload"
	@echo "  make dev-ui          - Run UI only with hot reload"
	@echo "  make dev-logs        - View development logs"
	@echo "  make dev-stop        - Stop development services"
	@echo "  make install         - Install Python dependencies"
	@echo "  make install-ui      - Install UI dependencies"
	@echo "  make test            - Run tests"
	@echo "  make lint            - Run linter"
	@echo "  make format          - Format code"
	@echo ""
	@echo "Sandbox Direct Run (sandbox.meridyen.ai):"
	@echo "  make sandbox         - Build UI & run backend (production)"
	@echo "  make sandbox-dev     - Run backend + UI with hot reload"
	@echo "  make sandbox-stop    - Stop sandbox processes"
	@echo ""
	@echo "Rebuild (pick stack with SANDBOX_COMPOSE=…):"
	@echo "  make rebuild-sandbox      - Rebuild sandbox image + recreate sandbox container only (keeps DB volume)"
	@echo "  make rebuild-sandbox-full - build-ui + rebuild sandbox + recreate all services (postgres, frontend if in compose)"
	@echo "  Example standalone stack: make rebuild-sandbox-full SANDBOX_COMPOSE=docker-compose.sandbox.yaml"
	@echo ""
	@echo "Cleanup Commands:"
	@echo "  make clean           - Remove containers and volumes"
	@echo "  make clean-all       - Remove everything including images"

# =============================================================================
# Build Commands
# =============================================================================

# Rebuild only the sandbox app image and container; does not touch postgres data or run frontend build.
rebuild-sandbox:
	docker compose -f $(SANDBOX_COMPOSE) build --no-cache sandbox
	docker compose -f $(SANDBOX_COMPOSE) up -d --no-deps --force-recreate sandbox
	@echo "✅ Sandbox service rebuilt (compose: $(SANDBOX_COMPOSE))"

# Rebuild frontend (npm), sandbox image, and recreate every service in the compose file (postgres + optional frontend).
rebuild-sandbox-full: build-ui
	docker compose -f $(SANDBOX_COMPOSE) build --no-cache sandbox
	docker compose -f $(SANDBOX_COMPOSE) up -d --build --force-recreate
	@echo "✅ Full rebuild done (compose: $(SANDBOX_COMPOSE)) — DB volume kept; use 'make clean' first to wipe DB data"

build:
	docker build -t meridyen/sandbox:latest .
	@echo "✅ Build complete: meridyen/sandbox:latest"

build-airgapped:
	docker build -f Dockerfile.airgapped -t meridyen/sandbox-airgapped:latest .
	@echo "✅ Build complete: meridyen/sandbox-airgapped:latest"

build-dev:
	docker build --target development -t meridyen/sandbox:dev .
	@echo "✅ Development build complete: meridyen/sandbox:dev"

push:
	docker push meridyen/sandbox:latest
	docker push meridyen/sandbox-airgapped:latest
	@echo "✅ Images pushed to Docker Hub"

# =============================================================================
# Run Commands
# =============================================================================

run:
	@if [ ! -f config/sandbox.yaml ]; then \
		echo "⚠️  config/sandbox.yaml not found. Copying example..."; \
		cp config/sandbox.example.yaml config/sandbox.yaml; \
		echo "📝 Please edit config/sandbox.yaml with your settings"; \
		exit 1; \
	fi
	docker compose -f docker-compose.hybrid.yaml up -d
	@echo "✅ Sandbox running in hybrid mode"
	@echo "   REST API: http://localhost:8080"
	@echo "   gRPC:     localhost:50051"
	@echo "   Metrics:  http://localhost:9090/metrics"

run-airgapped:
	@if [ ! -f config/sandbox.yaml ]; then \
		echo "⚠️  config/sandbox.yaml not found. Copying example..."; \
		cp config/sandbox.example.yaml config/sandbox.yaml; \
		echo "📝 Please edit config/sandbox.yaml with your settings"; \
		exit 1; \
	fi
	docker compose -f docker-compose.airgapped.yaml up -d
	@echo "✅ Sandbox running in air-gapped mode"

stop:
	docker compose -f docker-compose.hybrid.yaml down 2>/dev/null || true
	docker compose -f docker-compose.airgapped.yaml down 2>/dev/null || true
	@echo "✅ Sandbox stopped"

restart: stop run

logs:
	docker compose -f docker-compose.hybrid.yaml logs -f sandbox 2>/dev/null || \
	docker compose -f docker-compose.airgapped.yaml logs -f sandbox

# =============================================================================
# Development Commands
# =============================================================================

dev:
	@echo "Starting development environment..."
	docker compose -f docker-compose.hybrid.yaml -f docker-compose.dev.yaml up -d
	@echo "✅ Development sandbox running"
	@echo "   REST API: http://localhost:8080"
	@echo "   Docs:     http://localhost:8080/docs"

install:
	pip install --user --break-system-packages -e "." 2>/dev/null || pip install -e "."
	@echo "✅ Development dependencies installed"

test:
	pytest tests/ -v --cov=sandbox --cov-report=term-missing

test-quick:
	pytest tests/ -v -x --tb=short

lint:
	ruff check src/sandbox
	mypy src/sandbox --ignore-missing-imports

format:
	black src/sandbox tests
	ruff check src/sandbox --fix

# Generate gRPC code from proto
proto:
	python -m grpc_tools.protoc \
		-I src/sandbox/proto \
		--python_out=src/sandbox/proto \
		--grpc_python_out=src/sandbox/proto \
		src/sandbox/proto/sandbox.proto
	@echo "✅ Proto files generated"

# =============================================================================
# Cleanup Commands
# =============================================================================

clean:
	docker compose -f docker-compose.hybrid.yaml down -v 2>/dev/null || true
	docker compose -f docker-compose.airgapped.yaml down -v 2>/dev/null || true
	rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Cleanup complete"

clean-all: clean
	docker rmi meridyen/sandbox:latest 2>/dev/null || true
	docker rmi meridyen/sandbox-airgapped:latest 2>/dev/null || true
	docker rmi meridyen/sandbox:dev 2>/dev/null || true
	@echo "✅ Full cleanup complete"

# =============================================================================
# Utility Commands
# =============================================================================

shell:
	docker exec -it meridyen-sandbox /bin/bash

health:
	@curl -s http://localhost:8080/health | python -m json.tool

capabilities:
	@curl -s http://localhost:8080/capabilities | python -m json.tool

# Download Ollama models for air-gapped deployment
download-models:
	@echo "Downloading models for air-gapped deployment..."
	@mkdir -p models
	docker run --rm -v $(PWD)/models:/root/.ollama ollama/ollama pull llama3:8b
	@echo "✅ Models downloaded to ./models"

# =============================================================================
# UI Commands
# =============================================================================

install-ui:
	cd frontend && npm install
	@echo "✅ UI dependencies installed"

build-ui:
	cd frontend && npm run build
	@echo "✅ UI build complete"

dev-ui:
	@echo "Starting UI development server..."
	@echo "Make sure sandbox backend is running on http://localhost:8080"
	cd frontend && npm run dev

dev-backend:
	@echo "Starting Python sandbox backend with auto-reload..."
	@echo "Make sure you have Python dependencies installed (pip install -e .)"
	@echo "Hot reload enabled - changes will restart the server automatically"
	cd src && uvicorn sandbox.main:app --reload --host 0.0.0.0 --port 8080

dev-backend-basic:
	@echo "Starting Python sandbox backend (no auto-reload)..."
	cd src && python -m sandbox.main

dev-full:
	@echo "Starting sandbox backend and UI with hot reloading (Docker Compose)..."
	@echo ""
	@echo "🔥 Hot Reload Enabled:"
	@echo "   Backend (Uvicorn):  http://localhost:8080 (API docs: /docs)"
	@echo "   Frontend (Vite):    http://localhost:5173"
	@echo ""
	@echo "📝 Changes to Python or React files will auto-reload"
	@echo "🛑 Press Ctrl+C to stop all services"
	@echo ""
	docker compose -f docker-compose.hybrid.yaml -f docker-compose.dev.yaml up --build

dev-full-detached:
	@echo "Starting sandbox backend and UI in background..."
	docker compose -f docker-compose.hybrid.yaml -f docker-compose.dev.yaml up -d --build
	@echo ""
	@echo "✅ Services running in background:"
	@echo "   Backend:  http://localhost:8080"
	@echo "   Frontend: http://localhost:5173"
	@echo ""
	@echo "View logs: make dev-logs"
	@echo "Stop:      make dev-stop"

dev-stop:
	docker compose -f docker-compose.hybrid.yaml -f docker-compose.dev.yaml down
	@echo "✅ Development services stopped"

dev-logs:
	docker compose -f docker-compose.hybrid.yaml -f docker-compose.dev.yaml logs -f

dev-restart:
	@make dev-stop
	@make dev-full-detached

dev-local:
	@echo "Starting sandbox backend and UI locally (no Docker)..."
	@echo ""
	@echo "Frontend (Vite): Hot reload on http://localhost:5173"
	@echo "Backend (Uvicorn): Auto-reload on http://localhost:8080"
	@echo ""
	@echo "Press Ctrl+C to stop both services"
	@trap 'kill 0' INT; \
	(cd src && uvicorn sandbox.main:app --reload --host 0.0.0.0 --port 8080) & \
	(cd frontend && npm run dev)

run-with-ui: build-ui
	@if [ ! -f config/sandbox.yaml ]; then \
		echo "⚠️  config/sandbox.yaml not found. Copying example..."; \
		cp config/sandbox.example.yaml config/sandbox.yaml; \
		echo "📝 Please edit config/sandbox.yaml with your settings"; \
		exit 1; \
	fi
	docker compose -f docker-compose.hybrid.yaml up -d
	@echo "✅ Sandbox running with UI"
	@echo "   Web UI:   http://localhost:5173"
	@echo "   REST API: http://localhost:8080"
	@echo "   gRPC:     localhost:50051"
	@echo "   Metrics:  http://localhost:9090/metrics"

# =============================================================================
# Sandbox Docker Run (for sandbox.meridyen.ai)
# =============================================================================
# Runs sandbox backend + frontend in Docker containers

sandbox: build-ui
	@echo "Starting Meridyen Sandbox (production mode in Docker)..."
	docker compose -f docker-compose.sandbox.yaml up -d --build
	@echo ""
	@echo "Backend + Frontend on port $${SANDBOX_REST_PORT:-38082}"

sandbox-dev:
	@echo "Starting Meridyen Sandbox (development mode in Docker)..."
	docker compose -f docker-compose.sandbox.yaml up --build
	@echo ""
	@echo "Frontend (Vite):    http://localhost:$${SANDBOX_FRONTEND_PORT:-5180}"
	@echo "Backend (Uvicorn):  http://localhost:$${SANDBOX_REST_PORT:-38082}"

sandbox-stop:
	@echo "Stopping sandbox containers..."
	docker compose -f docker-compose.sandbox.yaml down
	@echo "Sandbox stopped"

sandbox-logs:
	docker compose -f docker-compose.sandbox.yaml logs -f
