# Task runner. On Windows without `make`, use scripts/tasks.ps1 instead:
#   ./scripts/tasks.ps1 test

PY := backend/.venv/Scripts/python.exe
ifeq ($(OS),)
	PY := backend/.venv/bin/python
endif

.PHONY: help setup dev-backend dev-frontend test lint fmt typecheck migrate migration check clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## Create the venv, install all dependencies, apply migrations
	python -m venv backend/.venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e "backend[dev,embeddings-fast]"
	cd backend && ../$(PY) -m alembic upgrade head
	npm --prefix frontend install

dev-backend: ## Run the API with hot reload
	cd backend && ../$(PY) -m uvicorn app.main:create_app --factory --reload --port 8000

dev-frontend: ## Run the Next.js dev server
	npm --prefix frontend run dev

test: ## Run the backend test suite
	cd backend && ../$(PY) -m pytest

lint: ## Lint both sides
	cd backend && ../$(PY) -m ruff check app tests
	npm --prefix frontend run lint

fmt: ## Format the backend
	cd backend && ../$(PY) -m ruff format app tests alembic
	cd backend && ../$(PY) -m ruff check --fix app tests

typecheck: ## Type-check both sides
	cd backend && ../$(PY) -m mypy app
	npm --prefix frontend exec tsc -- --noEmit

migrate: ## Apply pending migrations
	cd backend && ../$(PY) -m alembic upgrade head

migration: ## Autogenerate a migration: make migration m="add chat tables"
	cd backend && ../$(PY) -m alembic revision --autogenerate -m "$(m)"

check: lint typecheck test ## Everything CI runs

clean: ## Remove build and cache artefacts
	rm -rf backend/.pytest_cache backend/.ruff_cache backend/.mypy_cache
	rm -rf frontend/.next frontend/node_modules/.cache
