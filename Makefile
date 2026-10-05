.PHONY: up down logs migrate test test-backend test-frontend lint lint-backend lint-frontend format services

COMPOSE := docker compose

up: ## Build and start every service (postgres, redis, backend, worker, frontend)
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example; set FERNET_KEY and AUTH_SECRET")
	$(COMPOSE) up -d --build --renew-anon-volumes
	@echo "Frontend: http://localhost:3000   API: http://localhost:8000/health"

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

migrate: ## Apply database migrations inside the backend container
	$(COMPOSE) run --rm backend alembic upgrade head

services: ## Just postgres + redis, for running tests on the host
	$(COMPOSE) up -d --wait postgres redis

test: test-backend test-frontend

test-backend: services
	cd backend && uv run pytest

test-frontend:
	cd frontend && npm run typecheck

lint: lint-backend lint-frontend

lint-backend:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy

lint-frontend:
	cd frontend && npm run lint && npm run format:check

format:
	cd backend && uv run ruff check --fix . && uv run ruff format .
	cd frontend && npm run format
