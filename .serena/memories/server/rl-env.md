# RL env (R0, on main, 2026-10-02)

Files: `ml/env.py` (HandEnv, encode_obs, replay_hand), `ml/vec_env.py` (VecHandEnv,
SubprocVecHandEnv, episode_seed), `ml/fast_encode.py` (encode_state, encode_reference),
`ml/bench_env.py`, `ml/mp.py` (mp_context, moved out of generate_dataset). Tests:
`tests/test_ml_{env,vec_env,fast_encode,bench_env}.py`. Doc: docs/06-ml.md §7 (API tables), §13
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
- Measured (i7-1265U): engine 7.2k dec/s/core; 10 workers: 24.5k engine-only, 18.2k with fast
  encode + dummy batched forward.
