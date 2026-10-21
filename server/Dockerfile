# syntax=docker/dockerfile:1.7
# 3.13 not 3.14: broadest current wheel coverage. torch has no cp313 wheels before
# 2.6 (see the `ml` extra in pyproject.toml) — bump this only alongside that pin.

FROM python:3.13-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/
WORKDIR /app

FROM base AS deps
COPY pyproject.toml uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# torch + cuda pins only, so an unrelated uv.lock bump leaves deps-ml's torch layer cached
FROM base AS torch-pins
COPY pyproject.toml uv.lock* ./
RUN uv export --frozen --no-dev --extra ml --no-hashes --no-emit-project \
    | grep -E '^(torch|triton|nvidia-|cuda-)' > /torch.txt

FROM base AS deps-ml
COPY --from=torch-pins /torch.txt /tmp/torch.txt
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /app/.venv && uv pip install --python /app/.venv --no-deps -r /tmp/torch.txt
COPY pyproject.toml uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --extra ml

FROM base AS dev
COPY pyproject.toml uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen
COPY . .
EXPOSE 8000
# ws frame cap and no permessage-deflate: docs/protocol.md §1
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--limit-concurrency", "1000", \
     "--ws-max-size", "65536", "--ws-per-message-deflate", "false", "--reload"]

FROM base AS prod
COPY --from=deps /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
COPY . .
RUN useradd --system --uid 1001 --no-create-home app && chown -R app:app /app
USER app
EXPOSE 8000
# one worker only: tables are in-memory, owned by one process. docs/infra.md §3
# ws frame cap and no permessage-deflate: docs/protocol.md §1
# --limit-concurrency: open connections + tasks before uvicorn answers 503. docs/infra.md §3
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--limit-concurrency", "1000", \
     "--ws-max-size", "65536", "--ws-per-message-deflate", "false"]

# torch only in this target
FROM base AS ml
COPY --from=deps-ml /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
COPY . .
RUN useradd --system --uid 1001 --no-create-home app && chown -R app:app /app
USER app
CMD ["python", "-m", "ml.train", "--help"]
