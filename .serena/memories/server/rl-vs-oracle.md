# agent vs ORACLE (2026-10-12, merged in b72e534)
- `ml.eval_policy --opponent ORACLE` now works: opponent seats via `bots.arena._view_for`; candidate/PolicyBot seats always `seat_view`. `--candidate-bot NAME` for heuristic calibration (never omniscient).
- results (hk_classic, seeds 8,000,000+, 1000 sets): L274.3M x1 vs ORACLE x3 +2.88 [1.75,4.01]; ORACLE x1 vs L274.3M x3 -1.53. agent already outscores ORACLE -> ORACLE is a defence probe, not a ceiling.
- vs ORACLE the agent gets zero ron wins (ORACLE never deals in, plays closed); its edge is big self-draws.
- raw results + scratch tools (analyze.py decision replay, bot_vs_agents.py 1xbot vs 3xpolicy, decompose.py): server/runs/oracle_gap/ (gitignored).
- gotcha: running worktree code with main's venv: `PYTHONPATH=. /home/michaels/Desktop/mahjong/server/.venv/bin/python ...` from worktree server/; `python -m` picks local modules.
- docs/ml.md §3 records the outcome; ml.md §12 frames ORACLE as a defence probe.
