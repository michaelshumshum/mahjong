# Task completion

1. Tests: `make test-server` (server-only change), `make test-web` (web-only), `make test` otherwise.
2. `make lint` (ruff check + oxlint/oxfmt --check); `make fmt` to fix formatting.
3. Web type check: `make typecheck` (svelte-check).
4. Touched `server/app/protocol.py` → `make proto`, commit generated output.
5. Visible UI change → `pnpm --dir web run screenshots`, inspect PNGs, update README Screenshots if content changed.
6. Update the relevant `docs/` file in the same change.

lefthook pre-commit runs oxlint, oxfmt --check, `pnpm check`, ruff format, ruff check on staged files.
