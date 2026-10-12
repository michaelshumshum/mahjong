# LearnedBot / T4 "Expert" (R4)
- `bots/learned.py` serves the RL policy: `policy_raw_from_view` -> `encode_policy_batch` -> `NumpyPolicyNet` -> masked argmax. numpy only; raises on a view with `.hands`.
- import boundary: outside `ml/`, only `bots/learned.py` may import `ml.*`, and only `ml.raw`, `ml.encode`, `ml.encode_v2`, `ml.export` (torch-free). `tests/test_learned_bot.py::test_serving_never_imports_torch` pins the exact `ml.*` module set in a fresh interpreter: a new import in those modules fails it.
- weights: `server/bots/weights/learned.npz`, committed (1.7 MB). Provenance in the npz `__meta__` (`ml.export.load_meta`). Test pins `engine_version == ENGINE_VERSION`: an engine bump that touches the ruleset encoding needs a re-export (`python -m ml.export --ckpt <league ckpt> --out bots/weights/learned.npz`), plus updating the pinned source/decisions in the test.
- tier id `T4`; `T3` stays retired (SearchBot, ADR 0012). Default/showcase/handover stay `T2`. Practice tiers: `app/main.py` `_PRACTICE_BOT_TIERS`, web `PRACTICE_DIFFICULTY_TO_TIER` (keep in sync; not in protocol schema).
- gate the production path with `ml.eval_policy --candidate-bot LearnedBot` (not `--ckpt`). Greedy numpy actions == torch `PolicyBot` actions (`tests/test_ml_learned_parity.py`).
- worker imports `bots.learned` lazily; weights cached per process (`functools.cache`). `OPENBLAS_NUM_THREADS=1` is set in `bots/learned.py` before numpy import.
- R4 results/history: `docs/ml.md §14` R4, `docs/rl-learnings.md §4`. scratch: `server/runs/r4_gate/` (gitignored: run.sh, pool_load.py).
- gotcha: lefthook's pre-commit `git stash create` fails on `git add -N` (intent-to-add) entries; stage new files fully or not at all.
