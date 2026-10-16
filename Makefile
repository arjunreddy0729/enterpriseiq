# EnterpriseIQ. Run `make` for the list.
#
# Every target here is a command that appears somewhere in the README or CI.
# If you change how something is run, change it here too - a Makefile that
# drifts from CI is worse than no Makefile.

BACKEND := backend
PY      := $(BACKEND)/.venv/bin/python
VENV    := $(BACKEND)/.venv

.DEFAULT_GOAL := help
.PHONY: help setup up down logs migrate seed ingest sync-github check lint format \
        typecheck test test-unit test-integration test-security eval eval-full \
        chunks clean

help: ## Show this list
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# --- setup ------------------------------------------------------------------
setup: ## Create the venv and install everything (first run)
	python3.12 -m venv $(VENV) 2>/dev/null || python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q --upgrade pip
	$(VENV)/bin/pip install -q --index-url https://download.pytorch.org/whl/cpu torch
	cd $(BACKEND) && .venv/bin/pip install -q -e ".[ml,parsers,dev]"
	@echo "ready. next: cp .env.example .env, then make up"

up: ## Start Postgres + the API (docker compose)
	docker compose up -d --build
	@echo "api:  http://localhost:$${API_HOST_PORT:-8000}/docs"

down: ## Stop the stack (keeps data)
	docker compose down

logs: ## Tail the API logs
	docker compose logs -f api

# --- data -------------------------------------------------------------------
migrate: ## Apply database migrations
	cd $(BACKEND) && .venv/bin/alembic upgrade head

seed: ## Create the demo groups and users
	cd $(BACKEND) && .venv/bin/python -m scripts.seed_users

ingest: ## Sync the local demo corpus into the index
	cd $(BACKEND) && .venv/bin/python -m scripts.sync_source local

sync-github: ## Sync a GitHub repo: make sync-github REPO=owner/name GROUPS=engineering
	@test -n "$(REPO)" || (echo "REPO=owner/name is required" && exit 1)
	cd $(BACKEND) && .venv/bin/python -m scripts.sync_source github \
		--repo $(REPO) --groups $(or $(GROUPS),engineering) $(if $(INCLUDE),--include $(INCLUDE),)

chunks: ## Inspect chunk boundaries: make chunks FILE=../corpus/hr/benefits.md
	cd $(BACKEND) && .venv/bin/python -m scripts.show_chunks $(or $(FILE),../corpus) $(if $(FILE),,--corpus)

# --- quality ----------------------------------------------------------------
check: lint typecheck test ## Everything CI runs

lint: ## Lint and check formatting
	cd $(BACKEND) && .venv/bin/ruff check . && .venv/bin/ruff format --check .

format: ## Apply formatting and safe lint fixes
	cd $(BACKEND) && .venv/bin/ruff check --fix . && .venv/bin/ruff format .

typecheck: ## Run mypy
	cd $(BACKEND) && .venv/bin/mypy app

test: ## Full test suite (integration tests need `make up`)
	cd $(BACKEND) && .venv/bin/python -m pytest

test-unit: ## Unit tests only - no database needed
	cd $(BACKEND) && .venv/bin/python -m pytest tests/unit

test-integration: ## Integration tests (needs the stack and an ingested corpus)
	cd $(BACKEND) && .venv/bin/python -m pytest tests/integration

test-security: ## The adversarial leak suite
	cd $(BACKEND) && .venv/bin/python -m pytest tests/security

# --- evaluation -------------------------------------------------------------
eval: ## Retrieval benchmark - no model calls, costs nothing
	cd $(BACKEND) && .venv/bin/python -m scripts.run_eval

eval-full: ## Full benchmark including generation (costs ~$1)
	cd $(BACKEND) && .venv/bin/python -m scripts.run_eval --full

clean: ## Remove caches and build artifacts
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.mypy_cache $(BACKEND)/.ruff_cache
