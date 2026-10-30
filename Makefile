# uv owns python, pnpm owns js, this file is the seam.

COMPOSE := docker compose
DC_PROD := docker compose -f docker-compose.yml -f docker-compose.prod.yml

# dev containers run as root through the bind mounts; chown what a run wrote back to the host
# user, keeping the command's exit status, or native tools hit EACCES (docs/infra.md §5)
HOST_IDS := $(shell id -u):$(shell id -g)
handback = sh -c '$(1); s=$$?; chown -R $(HOST_IDS) $(2) 2>/dev/null; exit $$s'
API_CACHES := .pytest_cache .ruff_cache .hypothesis
WEB_OUTPUTS := .svelte-kit src/lib/paraglide

.DEFAULT_GOAL := help
.PHONY: help up down restart logs build ps sh-api sh-web test test-server test-server-slow bench-latency test-web \
        selfplay arena train proto proto-check migrate revision fmt lint typecheck clean prod-build prod-up prod-migrate

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
	$(COMPOSE) run --rm --no-deps api $(call handback,uv run pytest -q -m fast -n auto,$(API_CACHES))

test-server-slow: ## pytest slow suite: soaks, real-bot e2e, hypothesis runs -- everything CI's server-slow job covers
	$(COMPOSE) run --rm --no-deps api \
		$(call handback,uv run pytest -q -m slow -n auto --games=$${N:-10000},$(API_CACHES))

bench-latency: ## latency tests serially against the absolute budget (docs/testing.md §1); run on the target CPU
	$(COMPOSE) run --rm --no-deps -e LATENCY_BUDGET_MS=$${BUDGET:-5} api uv run pytest -q -s -m latency -p no:xdist

# CI=true: vitest browser mode and playwright both default to *headed* off-CI, and the
# container has no X server. Set here, not in the compose service, so `make up`'s dev server
# isn't also told it's running in CI.
test-web: ## vitest + Playwright e2e
	$(COMPOSE) build web
	$(COMPOSE) run --rm --no-deps -e CI=true web \
		$(call handback,pnpm test,$(WEB_OUTPUTS) build test-results)

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
proto: ## Regenerate web protocol types and the learn-mode lesson bundle (+ shared/protocol.schema.json)
	$(COMPOSE) run --rm --no-deps api $(call handback,uv run python -m tools.gen_protocol \
		--ts-out /web-net/protocol.d.ts --schema-out /shared/protocol.schema.json,/web-net /shared)
	$(COMPOSE) run --rm --no-deps api \
		$(call handback,uv run python -m tools.gen_lessons --out /web-learn,/web-learn)
	$(COMPOSE) run --rm --no-deps web pnpm exec oxfmt \
		src/lib/net/protocol.d.ts src/lib/net/protocol.assertNever.ts src/lib/net/protocol.constants.ts \
		src/lib/learn/generated

proto-check: proto ## Fail if regenerating changes the committed output (CI gate; see docs/infra.md)
	@(git diff --exit-code shared/ web/src/lib/net/protocol.d.ts web/src/lib/net/protocol.assertNever.ts \
		web/src/lib/net/protocol.constants.ts web/src/lib/learn/generated \
		&& test -z "$$(git status --porcelain web/src/lib/learn/generated)") \
		|| (echo "\n  Generated output changed — run 'make proto' and commit it.\n" && exit 1)

migrate: ## Apply database migrations
	$(COMPOSE) exec api uv run alembic upgrade head

revision: ## Create a migration: make revision M="add games table"
	$(COMPOSE) exec api uv run alembic revision --autogenerate -m "$(M)"

# ── quality ───────────────────────────────────────────────────────────────────
fmt: ## Format both sides
	$(COMPOSE) run --rm --no-deps api $(call handback,uv run ruff format .,.ruff_cache)
	$(COMPOSE) run --rm --no-deps web pnpm exec oxfmt .

lint: ## Lint both sides
	$(COMPOSE) run --rm --no-deps api $(call handback,uv run ruff check .,.ruff_cache)
	$(COMPOSE) run --rm --no-deps web pnpm lint

typecheck: ## svelte-check
	$(COMPOSE) run --rm --no-deps web $(call handback,pnpm exec svelte-check,$(WEB_OUTPUTS))

# ── production shape ──────────────────────────────────────────────────────────
prod-build: ## Build production images
	$(DC_PROD) build

prod-up: ## Run the production overlay locally
	$(DC_PROD) up -d

prod-migrate: ## Apply migrations in the running prod api container
	$(DC_PROD) exec api alembic upgrade head

clean: ## Stop and delete volumes (DESTROYS the dev database)
	$(COMPOSE) down -v
