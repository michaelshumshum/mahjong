# Commands (run from repo root; all go through docker compose)

- `make up` / `make down` / `make logs` / `make restart` (recreate api) / `make sh-api` / `make sh-web`
- web http://localhost:5173, api http://localhost:8000/docs
- `make test` = `test-server` (pytest `-m fast -n auto`) + `test-web` (vitest + e2e, CI=true for headless)
- `make selfplay N=10000` — slow engine soak (`-m slow`)
- `make arena A=FaanBot B=EfficiencyBot N=20000`
- `make proto` — regen protocol types after touching `server/app/protocol.py`
- `make migrate` / `make revision M="msg"`
- `make fmt` / `make lint` / `make typecheck`
- `pnpm --dir web run screenshots` — regenerate `docs/screenshots/*.png` after visible UI changes (skill: frontend-screenshots)

## System notes
- Host shell for agents is fish; `sudo` has no TTY — use `pkexec`.
- Docker user is in `docker` group; no sudo needed for compose.
