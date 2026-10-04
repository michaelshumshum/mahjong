# RL env (R0, on main, 2026-10-02)

Files: `ml/env.py` (HandEnv, encode_obs, replay_hand), `ml/vec_env.py` (VecHandEnv,
SubprocVecHandEnv, episode_seed), `ml/fast_encode.py` (encode_state, encode_reference),
`ml/bench_env.py`, `ml/mp.py` (mp_context, moved out of generate_dataset). Tests:
`tests/test_ml_{env,vec_env,fast_encode,bench_env}.py`. Doc: docs/ml.md §7 (API tables), §13
(measured numbers), §14 (R0 progress).

Gotchas:
- Episode starts from `engine.new_hand(ruleset, seed, dealer, prevailing)`; `hand_start` draws
  both from `Random(f"start:{seed}")`. hk_classic is EAST_ONLY, so prevailing is always East there.
- Claim-order RNG is `Random(f"claims:{seed}")` (str seed) so it never correlates with a policy RNG
  seeded with the bare int.
- Single-legal-action auto-play is rare (~1 in 85 random hands); tests sweep 300 seeds to hit it.
- `seat_view` computes legal actions every call: the reference encoder path is ~0.14 ms/decision,
  same as the engine. Fast encoder is ~0.02 ms; engine now ~90% of env time.
- OpenBLAS threads in the parent (policy matmul) spin and starve env workers ~3x. bench_env sets
  OPENBLAS_NUM_THREADS=1 before numpy import; the PPO learner must pin torch/BLAS threads too.
- HandEnv.record() returns `HandRecord` columns (`app/db/records.hand_record_columns`); persist
  with `save_hand_record` into `hand_records` (alembic 3c1f6a2b9d4e), never `games`.
- Parity test was mutation-checked: dropping the other-seat concealed-kong skip fails it.
- Measured (i7-1265U) before engine speed-ups: engine 7.2k dec/s/core; 10 workers: 24.5k
  engine-only, 18.2k with fast encode + dummy batched forward.

## Engine speed-ups (R0 done, branch rl/r0-engine-speedups, 2026-10-02)
- After: 18.8k dec/s/core engine-only (2.7x), 13.9k with fast encode; 120x10: 62.5k / 32.1k.
  Laptop throttles: interleave before/after runs, best-of-N; base tree via `git archive`.
- `actions._is_winning_shape(concealed, closed=)` replaces `decompose(...) != ()` in
  `hand_is_winning_shape`; standard shape = per-suit lookup in `melds._SUIT_SHAPES` (eager
  dict, 21,743 complete suit vectors -> has-pair flag, ~15 ms at import, ~4 MB). Chose eager
  table over lazy functools.cache: lazy key space is ~273k suit vectors, unbounded growth.
- `engine._can_win_with` shape-checks the tuple before `dataclasses.replace` (most fail).
- `tiles._TILE_ID_TYPES` tuple lookup; range check kept (negative ids would wrap).
- Tried + reverted: batched `_tile_id_types` (min/max + list + zip) in legal_claims/
  legal_self_melds/_chow_options: ~6% SLOWER on <=14-tile hands.
- Left: dataclasses.replace ~20% of profile; legal_self_melds/legal_claims/_chow_options ~30%.
  Further gains need structural change (no replace, incremental per-seat counts) or mypyc.
- Guards: `tests/test_engine_trajectory_pin.py` (sha256 of actions/events/hand results/final
  state, canonical JSON so PYTHONHASHSEED-independent; regenerate via
  `uv run python -m tests.test_engine_trajectory_pin` only with an ENGINE_VERSION bump);
  `tests/test_winning_shape.py` (exhaustive suit table vs decompose, hypothesis vs old form,
  _can_win_with vs old form). Uniform-random bots almost never win, so the pin also uses a
  greedy min-shanten policy (~250 wins).
- No `tests/replays/` dir exists in the repo despite AGENTS.md mentioning it.
