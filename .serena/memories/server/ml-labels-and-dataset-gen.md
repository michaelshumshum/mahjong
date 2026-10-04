# ML: supervised pieces kept for the RL plan (updated 2026-10-02)

Direction (2026-10-02): the learned bot is a self-play RL policy independent of FaanBot,
docs/ml.md §6-§15 (milestones R0-R4). The old phases (learned tile_risk inside FaanBot,
afterstate evaluator, FaanBot distillation) are DROPPED; docs/08-rl.md was merged into ml.md.
Deleted: ml/heuristic_baseline.py, ml/gbdt_baseline.py, configs/bc.yaml, fit_platt/apply_platt,
play_and_label's row_hook, pettingzoo + lightgbm deps. Don't reintroduce FaanBot as a teacher,
reward baseline, feature source or training opponent (only §10's contingency bootstrap).

Kept (docs/ml.md §5): encoder, bots/labels.py, dataset gen/pack/splits, DangerNet + train/eval,
metrics, numpy export. DangerNet test results (v3, 1,125 test games): legal-wait AUC 0.889,
tenpai AUC 0.868; GBDT baseline 0.853; FaanBot deal_in_probability ~0.50 pooled (0.66 within
tenpai opponents; genbutsu factor is anti-correlated with tenpai since HK has no furiten).

**Labels — `bots/labels.py`:** pure `GameState`-based ground truth. `tests/test_oracle_containment.py`
forbids `_omniscient_seat_view` outside `Table._submit_bot_job`, so labels read `GameState`
directly. Faan values in `tests/test_labels.py` come from the real scorer (平糊/無花/門前清 stack, so a
plain closed tenpai hand scores 3).

**Local data (gitignored, cwd server/):** `data/danger_v3` (10,674 games), `data/danger_v3_packed`
(5.07M rows), `data/danger_v3_heldout_eff_packed` (2,000 EfficiencyBot games, NOT yet evaluated),
`runs/danger/ckpt_best.pt` + eval jsons. Repo-root `data/` is root-owned.

**Commands (cwd server/):** see docs/ml.md §5's code block (generate_dataset, pack, train,
evaluate, export).

**Gotchas:**
- Splits are game-level (`ml/splits.py`, TRAIN/VAL/TEST = 0/1/2).
- `test_ml_export.py`'s <5 ms latency test (slow-marked) fails under `-n 8` CPU contention,
  passes alone (~0.9 s run). Not a regression signal under parallel load.
- `tests/ml_synthetic.py` builds a synthetic packed dataset for ml tests.
- `ml.load_packed` needs a `Path`, not a str.
- lefthook comment-length hook: max 2 consecutive comment lines.
- numpy is not a base dependency; R4 serving adds it.
