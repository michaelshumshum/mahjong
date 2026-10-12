# RL policy behaviour analysis (2026-10-12)
- Tooling: `server/runs/behaviour/` in the main checkout (gitignored): `extract.py` (per-decision rows: policy probs, shanten per legal discard, exact deal-in per discard via `_view_for`), `aggregate.py` (tables, LABEL=rows.jsonl), `examples.py` (one seat-hand, decision by decision), `run.sh`/`resume.sh` (evals, seeds 12,000,000+).
- Results are in docs/rl-learnings.md §5 "Decision level" (branch docs/rl-behaviour-analysis).
- Gotchas: worktree-isolated agents get their worktree cleaned up mid-run, so long background jobs must not cd into it. The main checkout's server/.venv can lose torch (another session's `uv sync` without `--extra ml`), so use a worktree venv made with `uv sync --extra ml`.
- Open: a controlled suit-reading probe, and decision-level stats vs ORACLE and mixed tables.
