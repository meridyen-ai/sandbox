# =============================================================================
# Meridyen Sandbox Makefile
# =============================================================================

.PHONY: help build build-airgapped run run-airgapped stop dev test lint format clean

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
	@echo "  make dev             - Run sandbox in development mode"
	@echo "  make dev-ui          - Run UI in development mode"
	@echo "  make dev-full        - Run both sandbox and UI in development"
	@echo "  make test            - Run tests"
	@echo "  make lint            - Run linter"
	@echo "  make format          - Format code"
	@echo ""
	@echo "Cleanup Commands:"
	@echo "  make clean           - Remove containers and volumes"
	@echo "  make clean-all       - Remove everything including images"

# =============================================================================
# Build Commands
# =============================================================================

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
	docker-compose -f docker-compose.hybrid.yaml up -d
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
	docker-compose -f docker-compose.airgapped.yaml up -d
	@echo "✅ Sandbox running in air-gapped mode"

stop:
	docker-compose -f docker-compose.hybrid.yaml down 2>/dev/null || true
	docker-compose -f docker-compose.airgapped.yaml down 2>/dev/null || true
	@echo "✅ Sandbox stopped"

restart: stop run

logs:
	docker-compose -f docker-compose.hybrid.yaml logs -f sandbox 2>/dev/null || \
	docker-compose -f docker-compose.airgapped.yaml logs -f sandbox

# =============================================================================
# Development Commands
# =============================================================================

dev:
	@echo "Starting development environment..."
	docker-compose -f docker-compose.hybrid.yaml -f docker-compose.dev.yaml up -d
	@echo "✅ Development sandbox running"
	@echo "   REST API: http://localhost:8080"
	@echo "   Docs:     http://localhost:8080/docs"

install:
	pip install -e ".[dev]"
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
	docker-compose -f docker-compose.hybrid.yaml down -v 2>/dev/null || true
	docker-compose -f docker-compose.airgapped.yaml down -v 2>/dev/null || true
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
	cd frontend && npm run dev

dev-full:
	@echo "Starting sandbox backend and UI..."
	@make -j2 dev dev-ui

run-with-ui: build-ui
	@if [ ! -f config/sandbox.yaml ]; then \
		echo "⚠️  config/sandbox.yaml not found. Copying example..."; \
		cp config/sandbox.example.yaml config/sandbox.yaml; \
		echo "📝 Please edit config/sandbox.yaml with your settings"; \
		exit 1; \
	fi
	docker-compose -f docker-compose.hybrid.yaml up -d
	@echo "✅ Sandbox running with UI"
	@echo "   Web UI:   http://localhost:3000"
	@echo "   REST API: http://localhost:8080"
	@echo "   gRPC:     localhost:50051"
	@echo "   Metrics:  http://localhost:9090/metrics"
