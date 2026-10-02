# ML feature encoders (updated 2026-09-29)

Two encoders live in `server/ml/encode.py`; both read only entitled `SeatView` data (never
`view.hands`, the ORACLE tier's omniscient extra):

- `encode_seat_view(view)` / `encode_ruleset(ruleset)` (2026-09-28): seat-centred layout, 4-plane
  thermometers, relative-seat axes, context block. `encode_ruleset` = [min_faan, wall_reserve,
  hand_sets bitmask, effective faan per PATTERNS entry]. See docs/06-ml.md §5. The RL fast
  encoder (§7) must stay parity-tested against `encode_seat_view(seat_view(...))`.
- `encode_batch(raw, opp, ruleset_vec) -> (tiles (B,56,34), scalars (B,S))` (2026-09-29): the
  training-time encoder over packed raw arrays (`ml/pack.py`), one sample per (row, opponent) with
  seats rotated so the target opponent is first. Channels: hand thermometer, 4 seats' melds and
  discards, discard-recency buckets (target and others), unseen copies, static tile properties,
  wind/dragon markers, target-suji. `rows_to_arrays` builds the same raw dict from `raw_row`s.
  A test pins the thermometer convention to `encode_seat_view`.

`ml/raw.py` (numpy-free) is the one place view-derived columns are built (`raw_row`,
`visible_meld_counts34`), shared by dataset gen and the encoders. The concealed-kong leak (other
seats' concealed-kong tile types via `SeatView.melds`) is fixed there.

Model consumers: `ml/danger_model.py` (DangerNet, 37-wide padded tile axis, zero column between
suits), `ml/losses.py`, `ml/train.py`, `ml/dataset.py`. See `mem:server/ml-labels-and-dataset-gen`
for pipeline commands and status.

**Environment gotcha:** numpy/torch/pyarrow/pyyaml are `ml`-extra only; every ml test opens with
`pytest.importorskip` so the base image's fast suite still passes. `.github/workflows/
server-ml.yml` runs `tests/test_ml_*.py tests/test_generate_dataset.py` for real.
