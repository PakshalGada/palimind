# Palimind — single entry point for all common tasks.
# Works on Linux, macOS and Windows (via make from Git Bash / WSL / choco make).

BACKEND_DIR := packages/backend
FRONTEND_DIR := packages/frontend
DESKTOP_DIR := apps/desktop

.DEFAULT_GOAL := help

.PHONY: help dev build test lint fmt typecheck icons check-imports backend-test frontend-test frontend-build clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'

frontend-build: ## Build the frontend bundle
	npm run build --prefix $(FRONTEND_DIR)

dev: frontend-build ## Run the desktop app in dev mode (backend must be installed: pip install -e packages/backend)
	cd $(BACKEND_DIR) && python -m palimind.cli.main ui

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
	npm run lint --prefix $(FRONTEND_DIR)
	npm run build --prefix $(FRONTEND_DIR)

lint: ## Lint backend (ruff) and frontend (oxlint)
	cd $(BACKEND_DIR) && ruff check .
	npm run lint --prefix $(FRONTEND_DIR)

fmt: ## Format backend code with ruff
	cd $(BACKEND_DIR) && ruff format . && ruff check --fix .

typecheck: ## Run mypy on gated modules
	cd $(BACKEND_DIR) && mypy

icons: ## Generate all app icons from brand/icons/icon.svg
	./scripts/generate-icons.sh

check-imports: ## Fail if any legacy 'core' package references remain
	@! grep -rnE '(from|import)[[:space:]]+core([. ])|-m core\.|"core\.' \
		--include='*.py' --include='*.rs' --include='*.toml' --include='*.ps1' --include='*.sh' \
		--exclude-dir=target --exclude-dir=node_modules --exclude-dir=__pycache__ --exclude-dir=.venv \
		packages apps scripts dev.ps1 2>/dev/null || true

clean: ## Remove caches and build artifacts
	rm -rf $(BACKEND_DIR)/palimind/__pycache__ $(BACKEND_DIR)/tests/__pycache__
	rm -rf $(FRONTEND_DIR)/dist $(FRONTEND_DIR)/node_modules/.vite
	find . -name "*.pyc" -delete && find . -name "__pycache__" -type d -empty -delete
