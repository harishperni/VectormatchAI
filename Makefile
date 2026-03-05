.PHONY: backend frontend worker infra-up infra-down migrate dev-up dev-all

DATABASE_URL ?= postgresql+psycopg://postgres:postgres@localhost:5432/ats
REDIS_URL ?= redis://localhost:6379/0

backend:
	cd backend && DATABASE_URL="$(DATABASE_URL)" REDIS_URL="$(REDIS_URL)" uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

worker:
	cd worker && DATABASE_URL="$(DATABASE_URL)" REDIS_URL="$(REDIS_URL)" python -m app.main

infra-up:
	docker compose -f infra/docker-compose.yml up -d

infra-down:
	docker compose -f infra/docker-compose.yml down

migrate:
	cd backend && DATABASE_URL="$(DATABASE_URL)" python -m alembic upgrade head

dev-up: infra-up migrate
	@echo "Infra is up and DB migrations are applied."

dev-all:
	@echo "Starting backend, worker, and frontend in one shell. Ctrl+C to stop all."
	@trap 'kill 0' INT TERM EXIT; \
	$(MAKE) backend & \
	$(MAKE) worker & \
	$(MAKE) frontend & \
	wait
