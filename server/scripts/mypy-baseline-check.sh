#!/usr/bin/env bash
# Baseline-tolerant mypy gate, shared by CI (.github/workflows/server.yml) and the
# pre-commit hook (.pre-commit-config.yaml) so the threshold exists in exactly one place.
#
# mypy has pre-existing debt: BASELINE errors, all confined to test files (a handful of
# narrow mypy-narrowing false positives and untyped-Any edges in test helpers) -- not real
# bugs, and not something a routine change should be blocked on fixing. A hard `mypy .`
# gate with zero tolerance would make this check permanently red, so instead of demanding
# zero errors, this only fails when the count goes *up* from BASELINE.
#
# BASELINE should only ever move down (as debt is paid off) or be raised deliberately with
# justification in the commit that raises it -- never bumped silently just to turn a red
# check green.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

BASELINE=28

output=$(uv run mypy . 2>&1) || true
echo "$output"

if echo "$output" | grep -q '^Success: no issues found'; then
  count=0
else
  count=$(echo "$output" | grep -oE '^Found [0-9]+ error' | grep -oE '[0-9]+' || true)
  if [ -z "$count" ]; then
    echo "mypy-baseline-check: could not parse mypy output (see above) -- treating as failure." >&2
    exit 1
  fi
fi

echo "mypy-baseline-check: $count error(s), baseline $BASELINE"

if [ "$count" -gt "$BASELINE" ]; then
  echo "mypy-baseline-check: error count increased ($count > $BASELINE)." >&2
  echo "Fix the new error(s), or if this is accepted debt, raise BASELINE in" >&2
  echo "server/scripts/mypy-baseline-check.sh with justification." >&2
  exit 1
fi
