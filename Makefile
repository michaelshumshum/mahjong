# uv owns python, pnpm owns js, this file is the seam.

COMPOSE := docker compose
DC_PROD := docker compose -f docker-compose.yml -f docker-compose.prod.yml

.DEFAULT_GOAL := help
.PHONY: help up down restart logs build ps sh-api sh-web test test-server test-server-slow test-web \
        selfplay arena train proto proto-check migrate revision fmt lint typecheck clean prod-build prod-up

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ── everyday loop ─────────────────────────────────────────────────────────────
up: ## Start postgres + api + web
	$(COMPOSE) up -d --build --renew-anon-volumes
	@echo "  web  http://localhost:$${WEB_PORT:-5173}"
	@echo "  api  http://localhost:$${API_PORT:-8000}/docs"

down: ## Stop everything (volumes preserved)
	$(COMPOSE) down

restart: ## Recreate the api container
	$(COMPOSE) up -d --force-recreate api

logs: ## Tail all logs
	$(COMPOSE) logs -f --tail=100

ps: ## Show container status
	$(COMPOSE) ps

build: ## Rebuild images
	$(COMPOSE) build

sh-api: ## Shell into the api container
	$(COMPOSE) exec api bash

sh-web: ## Shell into the web container
	$(COMPOSE) exec web sh

# ── tests ─────────────────────────────────────────────────────────────────────
test: test-server test-web ## Run all tests

test-server: ## pytest (fast tests only; use `make test-server-slow` for the slow suite)
	$(COMPOSE) run --rm --no-deps api uv run pytest -q -m fast -n auto

test-server-slow: ## pytest slow suite: soaks, real-bot e2e, hypothesis runs -- everything CI's server-slow job covers
	$(COMPOSE) run --rm --no-deps api uv run pytest -q -m slow -n auto --games=$${N:-10000}

# CI=true: vitest browser mode and playwright both default to *headed* off-CI, and the
# container has no X server. Set here, not in the compose service, so `make up`'s dev server
# isn't also told it's running in CI.
test-web: ## vitest + Playwright e2e
	$(COMPOSE) build web
	$(COMPOSE) run --rm --no-deps -e CI=true web pnpm test

selfplay: ## Engine soak test: N complete games with random bots (default 10000)
	$(COMPOSE) run --rm --no-deps api uv run pytest -q -m slow -k selfplay \
		--games=$${N:-10000}

# ── bots / ML ─────────────────────────────────────────────────────────────────
arena: ## Bot evaluation: make arena A=FaanBot B=EfficiencyBot N=20000
	$(COMPOSE) --profile tools run --rm arena \
		uv run python -m bots.arena --a $${A:-FaanBot} --b $${B:-EfficiencyBot} \
		--games $${N:-20000} --parallel $${P:-8}

train: ## Training run: make train CONFIG=ml/configs/danger.yaml
	$(COMPOSE) --profile ml run --rm trainer \
		uv run python -m ml.train --config $${CONFIG:-ml/configs/danger.yaml}

# ── codegen / db ──────────────────────────────────────────────────────────────
proto: ## Regenerate web protocol types (+ shared/protocol.schema.json, informational)
	$(COMPOSE) run --rm --no-deps api uv run python -m tools.gen_protocol \
		--ts-out /web-net/protocol.d.ts --schema-out /shared/protocol.schema.json
	$(COMPOSE) run --rm --no-deps web pnpm exec oxfmt \
		src/lib/net/protocol.d.ts src/lib/net/protocol.assertNever.ts

proto-check: proto ## Fail if regenerating changes the committed output (CI gate; see docs/infra.md)
	@git diff --exit-code shared/ web/src/lib/net/protocol.d.ts web/src/lib/net/protocol.assertNever.ts \
		|| (echo "\n  Protocol types changed — run 'make proto' and commit them.\n" && exit 1)

migrate: ## Apply database migrations
	$(COMPOSE) exec api uv run alembic upgrade head

revision: ## Create a migration: make revision M="add games table"
	$(COMPOSE) exec api uv run alembic revision --autogenerate -m "$(M)"

# ── quality ───────────────────────────────────────────────────────────────────
fmt: ## Format both sides
	$(COMPOSE) run --rm --no-deps api uv run ruff format .
	$(COMPOSE) run --rm --no-deps web pnpm exec oxfmt .

lint: ## Lint both sides
	$(COMPOSE) run --rm --no-deps api uv run ruff check .
	$(COMPOSE) run --rm --no-deps web pnpm lint

typecheck: ## svelte-check
	$(COMPOSE) run --rm --no-deps web pnpm exec svelte-check

# ── production shape ──────────────────────────────────────────────────────────
prod-build: ## Build production images
	$(DC_PROD) build

prod-up: ## Run the production overlay locally
	$(DC_PROD) up -d

clean: ## Stop and delete volumes (DESTROYS the dev database)
	$(COMPOSE) down -v
