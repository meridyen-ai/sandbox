# =============================================================================
# Meridyen Sandbox Makefile
# =============================================================================

.PHONY: help build build-airgapped run run-airgapped stop dev test lint format clean sandbox sandbox-dev sandbox-stop \
       llm-up llm-stop llm-logs llm-status llm-bench llm-pull

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
	@echo "LLM Service (vLLM - OpenAI-Compatible API):"
	@echo "  make llm-up                            - Start LLM with sandbox (all GPUs)"
	@echo "  make llm-up GPUS=2                     - Start with specific GPU count"
	@echo "  make llm-up MODEL=deepseek-ai/DeepSeek-V3 GPUS=4"
	@echo "  make llm-up MODEL=meta-llama/Llama-3.3-70B-Instruct GPUS=2 CTX=16384"
	@echo "  make llm-stop                          - Stop LLM service"
	@echo "  make llm-logs                          - View LLM logs"
	@echo "  make llm-status                        - Check model health & info"
	@echo "  make llm-bench                         - Quick latency benchmark"
	@echo "  make llm-pull MODEL=...                - Pre-download model weights"
	@echo ""
	@echo "Sandbox Direct Run (sandbox.meridyen.ai):"
	@echo "  make sandbox         - Build UI & run backend (production)"
	@echo "  make sandbox-dev     - Run backend + UI with hot reload"
	@echo "  make sandbox-stop    - Stop sandbox processes"
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
	docker compose -f docker-compose.sandbox.yaml -f docker-compose.llm.yaml down 2>/dev/null || true
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
	docker compose -f docker-compose.sandbox.yaml -f docker-compose.llm.yaml down -v 2>/dev/null || true
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

# =============================================================================
# LLM Service Commands (vLLM with OpenAI-Compatible API)
# =============================================================================
# Configurable via parameters:
#   GPUS    - Number of GPUs (default: all). Sets both device count and tensor parallelism.
#   MODEL   - HuggingFace model ID (default: meta-llama/Llama-3.3-70B-Instruct)
#   CTX     - Max context/sequence length (default: 8192)
#   HF_TOKEN - HuggingFace token for gated models

# Defaults
GPUS   ?= all
MODEL  ?= meta-llama/Llama-3.3-70B-Instruct
CTX    ?= 8192

# Resolve tensor parallel size: "all" means use 1 (vLLM auto-detects), numeric = use that count
ifeq ($(GPUS),all)
  _TP_SIZE = 1
else
  _TP_SIZE = $(GPUS)
endif

# Common env exports for LLM compose
define LLM_ENV
	VLLM_GPU_COUNT=$(GPUS) \
	VLLM_TENSOR_PARALLEL=$(_TP_SIZE) \
	VLLM_MODEL=$(MODEL) \
	VLLM_MAX_MODEL_LEN=$(CTX)
endef

llm-up:
	@echo "Starting vLLM LLM service..."
	@echo "  Model:          $(MODEL)"
	@echo "  GPUs:           $(GPUS)"
	@echo "  Tensor Parallel: $(_TP_SIZE)"
	@echo "  Max Context:    $(CTX)"
	@echo ""
	$(LLM_ENV) docker compose -f docker-compose.sandbox.yaml -f docker-compose.llm.yaml up -d
	@echo ""
	@echo "vLLM starting up (model loading may take several minutes)..."
	@echo "  OpenAI API:  http://localhost:$${VLLM_PORT:-8000}/v1"
	@echo "  Models:      http://localhost:$${VLLM_PORT:-8000}/v1/models"
	@echo "  Health:      http://localhost:$${VLLM_PORT:-8000}/health"
	@echo "  Sandbox API: http://localhost:$${SANDBOX_REST_PORT:-38082}"
	@echo ""
	@echo "Monitor startup: make llm-logs"

llm-stop:
	docker compose -f docker-compose.sandbox.yaml -f docker-compose.llm.yaml down
	@echo "LLM service stopped"

llm-logs:
	docker compose -f docker-compose.sandbox.yaml -f docker-compose.llm.yaml logs -f vllm

llm-status:
	@echo "=== vLLM Health ==="
	@curl -sf http://localhost:$${VLLM_PORT:-8000}/health && echo " OK" || echo " UNAVAILABLE (still loading?)"
	@echo ""
	@echo "=== Loaded Models ==="
	@curl -sf http://localhost:$${VLLM_PORT:-8000}/v1/models | python3 -m json.tool 2>/dev/null || echo "Not ready yet"

llm-bench:
	@echo "Running quick inference benchmark..."
	@echo "--- First token latency (cold) ---"
	@curl -sf -w "\nTotal: %{time_total}s | TTFB: %{time_starttransfer}s\n" \
		-X POST http://localhost:$${VLLM_PORT:-8000}/v1/chat/completions \
		-H "Content-Type: application/json" \
		-d '{"model":"$(MODEL)","messages":[{"role":"user","content":"Say hello in one word."}],"max_tokens":16,"temperature":0}' \
		| python3 -c "import sys,json; r=json.load(sys.stdin); u=r.get('usage',{}); print(f'Prompt tokens: {u.get(\"prompt_tokens\",\"?\")}  Completion tokens: {u.get(\"completion_tokens\",\"?\")}  Response: {r[\"choices\"][0][\"message\"][\"content\"]}')" 2>/dev/null \
		|| echo "Service not ready"

llm-pull:
	@echo "Pre-downloading model: $(MODEL)..."
	docker run --rm \
		-e HF_TOKEN=$${HF_TOKEN:-} \
		-e HUGGING_FACE_HUB_TOKEN=$${HF_TOKEN:-} \
		-v meridyen-llm_vllm_models:/root/.cache/huggingface \
		python:3.11-slim \
		sh -c "pip install -q huggingface_hub && huggingface-cli download $(MODEL)"
	@echo "Model downloaded to vllm_models volume"
