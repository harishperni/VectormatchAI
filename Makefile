.PHONY: check-env setup backend frontend worker infra-up infra-down migrate dev-up dev-all

DATABASE_URL ?= postgresql+psycopg://postgres:postgres@localhost:5432/ats
WORKER_DATABASE_URL ?= postgresql://postgres:postgres@localhost:5432/ats
REDIS_URL ?= redis://localhost:6379/0
API_BASE_URL ?= http://127.0.0.1:8000
PYTHON311 ?= $(shell command -v python3.11 2>/dev/null || ([ -x /opt/homebrew/bin/python3.11 ] && echo /opt/homebrew/bin/python3.11) || true)

check-env:
	@bash scripts/dev-check.sh

setup: check-env
	@if [ -z "$(PYTHON311)" ]; then \
		echo "python3.11 is required in PATH."; \
		exit 1; \
	fi
	cd backend && \
		if [ ! -x ".venv/bin/python" ] || ! .venv/bin/python -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)' >/dev/null 2>&1; then \
			rm -rf .venv; \
			$(PYTHON311) -m venv .venv; \
		fi && \
		. .venv/bin/activate && \
		pip install -U pip && \
		pip install -r requirements.txt
	cd worker && \
		if [ ! -x ".venv/bin/python" ] || ! .venv/bin/python -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)' >/dev/null 2>&1; then \
			rm -rf .venv; \
			$(PYTHON311) -m venv .venv; \
		fi && \
		. .venv/bin/activate && \
		pip install -U pip && \
		pip install -r requirements.txt
	cd frontend && npm install

backend:
	cd backend && . .venv/bin/activate && DATABASE_URL="$(DATABASE_URL)" REDIS_URL="$(REDIS_URL)" python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

frontend:
	cd frontend && NEXT_PUBLIC_API_BASE_URL="$(API_BASE_URL)" npm run dev

worker:
	cd worker && . .venv/bin/activate && WORKER_DATABASE_URL="$(WORKER_DATABASE_URL)" DATABASE_URL="$(DATABASE_URL)" REDIS_URL="$(REDIS_URL)" python -m app.main

infra-up:
	docker compose -f infra/docker-compose.yml up -d

infra-down:
	docker compose -f infra/docker-compose.yml down

migrate:
	cd backend && . .venv/bin/activate && DATABASE_URL="$(DATABASE_URL)" python -m alembic upgrade head

dev-up: check-env infra-up migrate
	@echo "Infra is up and DB migrations are applied."

dev-all: setup dev-up
	@echo "Starting backend, worker, and frontend in one shell. Ctrl+C to stop all."
	@trap 'kill 0' INT TERM EXIT; \
	$(MAKE) backend & \
	$(MAKE) worker & \
	$(MAKE) frontend & \
	wait
