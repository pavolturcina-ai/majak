.PHONY: help install fmt lint typecheck test check db-reset db-migrate seed run

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install the package with dev extras (editable)
	pip install -e ".[dev,ocr]"

fmt: ## Format code with black + ruff --fix
	black src tests
	ruff check --fix src tests

lint: ## Lint with ruff
	ruff check src tests

typecheck: ## Type-check with mypy
	mypy src

test: ## Run the test suite
	pytest -q

check: lint typecheck test ## Run lint + typecheck + tests

db-reset: ## Reset the local Supabase DB and re-apply all migrations
	supabase db reset

db-migrate: ## Apply pending migrations to the linked project
	supabase db push

seed: ## Ingest seed/raw/* through the real pipeline
	python -m majak.seed.run

run: ## Start the FastAPI dev server
	uvicorn majak.api.main:app --reload --port 8000
