# ML feature-plane encoder (built 2026-09-28)

`server/ml/encode.py` implements docs/06-ml.md §6.2's Phase 1 encoder input:
`encode_seat_view(view: SeatView) -> EncodedSeatView` and `encode_ruleset(ruleset) -> np.ndarray`.

Key decisions (see docs/99-deferred.md "Feature-plane encoding" for the full writeup):
- Only reads entitled `SeatView` fields (own_hand, melds, discard_pools, concealed_counts).
  Deliberately never reads `view.hands` (the ORACLE tier's omniscient extra) — a network trained
  on oracle-only input wouldn't generalize to the redacted view it's served at real inference.
- Tile planes are thermometer-encoded (4 planes per 34 tile types: plane k lit where count > k),
  kong contributes 3 tiles matching `mahjong_core.shanten`'s convention.
- All per-seat axes reordered to relative seat (self=0, next, across, previous) via
  `_relative_seats`.
- Added a `context` block (turn/dealer/prevailing-wind/own-seat-wind/phase one-hots) beyond the
  literal 99-deferred spec text, justified because tile planes alone can't express whose turn it
  is or yakuhai exposure — both already load-bearing for the heuristic bots this encoder is meant
  to eventually feed into.
- `encode_ruleset` follows 99-deferred's exact scheme: [min_faan, wall_reserve, hand_sets bitmask
  (CLASSIC/NEW_6/NEW_18), effective faan per `PATTERNS` entry (36 slots, `faan_overrides.get(name,
  base_faan)`)]. Timing/fairness RuleSet fields intentionally excluded.

**Important environment gotcha, don't re-discover it:** numpy is `ml`-extra only, not a base
dependency (`pyproject.toml`). `server/tests/` is pytest's only testpath and gets collected by
`make test-server`/CI's `server`/`server-slow` jobs, which run in the base dev image *without* the
ml extra. `server/tests/test_ml_encode.py` therefore opens with
`np = pytest.importorskip("numpy")` / `ml_encode = pytest.importorskip("ml.encode")` before any
other import — verified directly (hid numpy from the venv, confirmed the file skips cleanly
instead of erroring, then confirmed the full fast suite still passes both with and without numpy
present). There is no pytest suite that runs with the ml extra yet — `.github/workflows/
server-ml.yml` only smoke-tests `import ml`/`ml.train --help`, it doesn't run pytest. If that ever
changes, `test_ml_encode.py` is already ready to run for real under it.

Not built yet: anything that consumes `EncodedSeatView` (the opponent-danger model itself, phase
1's actual network, `tile_risk` integration) — this is still a pure input-shaping function with no
trained weights anywhere. See `mem:server/oracle-tier-redesign` for the related ORACLE-tier design
this Phase 1 danger model is meant to eventually replace the heuristic half of.
