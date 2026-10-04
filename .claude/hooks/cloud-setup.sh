#!/bin/bash
set -euo pipefail

[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0

export PATH="$HOME/.local/bin:$PATH"
eval "$(mise activate bash)"

cd "$CLAUDE_PROJECT_DIR"
(cd server && uv sync --locked)
pnpm install --frozen-lockfile
pnpm --dir web exec playwright install --with-deps chromium
