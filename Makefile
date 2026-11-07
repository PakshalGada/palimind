# Palimind — single entry point for all common tasks.
# Works on Linux, macOS and Windows (via make from Git Bash / WSL / choco make).

BACKEND_DIR := packages/backend
FRONTEND_DIR := packages/frontend
DESKTOP_DIR := apps/desktop
DESKTOP_NATIVE_DIR := packages/desktop-native
DESKTOP_PKGS := -p agent-desktop-core -p agent-desktop-linux -p palimind-desktop

# Prefer the repo-local venv python (`./.venv/bin/python`) when present so
# `make dev` works without manual activation; fall back to `python` on PATH.
PY_BIN := python
ifneq ($(wildcard .venv/bin/python),)
PY_BIN := $(CURDIR)/.venv/bin/python
endif

.DEFAULT_GOAL := help

.PHONY: help dev build test lint fmt typecheck icons check-imports backend-test frontend-test frontend-deps frontend-build desktop-native desktop-bundle desktop-test desktop-dogfood desktop-x11-check desktop-x11-gate desktop-lint desktop-smoke agent-benchmark agent-benchmark-live agent-benchmark-vs-grok routing-probe clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'

# Re-run `npm install` whenever the manifest/lockfile changes (e.g. a pull
# that adds a dependency), not only when node_modules is missing.
$(FRONTEND_DIR)/node_modules/.package-lock.json: $(FRONTEND_DIR)/package.json $(FRONTEND_DIR)/package-lock.json
	npm install --prefix $(FRONTEND_DIR)
	@touch $@

frontend-deps: $(FRONTEND_DIR)/node_modules/.package-lock.json ## Install frontend deps if package files changed

frontend-build: frontend-deps ## Build the frontend bundle
	npm run build --prefix $(FRONTEND_DIR)

dev: frontend-build ## Run the desktop app in dev mode (backend must be installed: pip install -e packages/backend)
	cd $(BACKEND_DIR) && $(PY_BIN) -m palimind.cli.main ui

backend: ## Start only the FastAPI backend on :8000
	cd $(BACKEND_DIR) && python -m palimind.api_server

frontend-dev: ## Run only the React frontend via Vite
	npm run dev --prefix $(FRONTEND_DIR)

build: ## Build production installers for the current OS
	npm run build --prefix $(DESKTOP_DIR)

test: backend-test frontend-test ## Run all tests

backend-test: ## Run Python tests
	cd $(BACKEND_DIR) && python -m pytest -m "not integration"

frontend-test: ## Run frontend tests + typecheck + lint
	npm test --prefix $(FRONTEND_DIR)
	npm run lint --prefix $(FRONTEND_DIR)
	npm run build --prefix $(FRONTEND_DIR)

lint: ## Lint backend (ruff) and frontend (oxlint)
	cd $(BACKEND_DIR) && ruff check .
	npm run lint --prefix $(FRONTEND_DIR)

fmt: ## Format backend code with ruff
	cd $(BACKEND_DIR) && ruff format . && ruff check --fix .

typecheck: ## Run mypy on gated modules
	cd $(BACKEND_DIR) && mypy


# --- Computer use: Linux desktop-native layer -------------------------------
desktop-native: ## Build the palimind-desktop native binary
	cd $(DESKTOP_NATIVE_DIR) && cargo build -p palimind-desktop

desktop-bundle: ## Build and stage the sidecar in the Tauri binaries/ directory
	./scripts/build-desktop-native.sh

desktop-test: ## Run the vendored engine + Palimind native tests
	cd $(DESKTOP_NATIVE_DIR) && cargo test $(DESKTOP_PKGS)

desktop-lint: ## Clippy the native workspace with warnings denied
	cd $(DESKTOP_NATIVE_DIR) && cargo clippy $(DESKTOP_PKGS) --all-targets -- -D warnings

desktop-smoke: ## Print platform, AT-SPI and kernel-input status
	cd $(DESKTOP_NATIVE_DIR) && cargo run --quiet -p palimind-desktop -- status

desktop-dogfood: desktop-bundle ## Run the 20-task Linux dogfood benchmark
	$(PY_BIN) scripts/desktop_dogfood.py --json /tmp/palimind-dogfood.json

desktop-x11-check: ## Run the X11 release-gate harness on the current display
	$(PY_BIN) scripts/x11_validation.py --json /tmp/palimind-x11.json

desktop-x11-gate: ## Run the X11 gate on a nested Xephyr + openbox display
	./scripts/run-x11-gate.sh

# --- Agent capability benchmark --------------------------------------------
AGENT_BENCH_MODEL ?= qwen3.5:4b
AGENT_BASELINE_MODEL ?= grok-4.7
AGENT_BASELINE_URL ?= https://opencode.ai/zen/go/v1

agent-benchmark: ## Deterministic agent capability benchmark (no model needed)
	$(PY_BIN) scripts/agent_capability_benchmark.py --mode scripted \
		--json benchmarks/agent-capability-scripted.json

agent-benchmark-live: ## Run the agent capability benchmark against a local model
	$(PY_BIN) scripts/agent_capability_benchmark.py --mode live \
		--model $(AGENT_BENCH_MODEL) --json benchmarks/agent-capability-live.json

agent-benchmark-vs-grok: ## Head-to-head local model vs hosted Grok baseline
	$(PY_BIN) scripts/agent_capability_benchmark.py --mode live \
		--model $(AGENT_BENCH_MODEL) \
		--baseline-model $(AGENT_BASELINE_MODEL) \
		--baseline-url $(AGENT_BASELINE_URL) \
		--json benchmarks/agent-capability-vs-grok.json

routing-probe: ## Prove capability routing on a hard task (local vs frontier)
	PALIMIND_AGENT_MODEL_ROUTING=off $(PY_BIN) scripts/routing_live_probe.py \
		--model $(AGENT_BENCH_MODEL) --json benchmarks/routing-live-local.json
	PALIMIND_AGENT_MODEL_ROUTING=auto \
		PALIMIND_FRONTIER_MODELS=$(AGENT_BASELINE_MODEL) \
		$(PY_BIN) scripts/routing_live_probe.py --model $(AGENT_BENCH_MODEL) \
		--json benchmarks/routing-live-frontier.json

icons: ## Generate all app icons from brand/icons/icon.svg
	./scripts/generate-icons.sh

check-imports: ## Fail if any legacy 'core' package references remain
	@! grep -rnE '(from|import)[[:space:]]+core([. ])|-m core\.|"core\.' \
		--include='*.py' --include='*.rs' --include='*.toml' --include='*.ps1' --include='*.sh' \
		--exclude-dir=target --exclude-dir=node_modules --exclude-dir=__pycache__ --exclude-dir=.venv \
		packages apps scripts dev.ps1 2>/dev/null

clean: ## Remove caches and build artifacts
	rm -rf $(BACKEND_DIR)/palimind/__pycache__ $(BACKEND_DIR)/tests/__pycache__
	rm -rf $(FRONTEND_DIR)/dist $(FRONTEND_DIR)/node_modules/.vite
	find . -name "*.pyc" -delete && find . -name "__pycache__" -type d -empty -delete
