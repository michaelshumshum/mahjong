# RL PPO cold start (R2, branch rl/r2-cold-start, 2026-10-03)

Files: `ml/train_env.py` (EnvConfig, TrainEnv, VecTrainEnv, SubprocVecTrainEnv, packed rows),
`ml/ppo.py` (Learner, Collector, PopArt, OracleAdapter, gae, shaped_rewards, train_ppo),
`ml/curriculum.py` (StageSpec, DEFAULT_STAGES, Curriculum, Contingency), `ml/eval_policy.py`
(PolicyBot, evaluate), `ml/configs/rl_ppo_c0.yaml`. `ml.train` dispatches `algorithm: ppo`
before `load_config` (PPOConfig is its own schema). Tests: `tests/test_ml_{train_env,ppo,
curriculum,eval_policy}.py`. Doc: docs/06-ml.md §7 (train env), §9, §10, §12, §13, §14.

Gotchas:
- Rows are one flat uint8 vector (`ROW_FIELDS`, `unpack_rows` returns views). Oracle rows always
  carry all 13 draws; per-sample `k` and the Bernoulli keep mask (packbits) are applied at encode
  time and stored per sample so the PPO update replays the exact behaviour input.
- OracleAdapter is a bias-free zero-init conv added after the trunk stem (`stem_bias` arg on
  `Trunk`/`PolicyNet.forward`). Bias-free is load-bearing: blind rows (all-zero oracle) must add
  exactly 0, or keep prob 0 would not equal the served PolicyNet.
- Values are recomputed by the critic at update time (no critic forward in rollout). Hands
  straddling an update finish into the next batch with their old behaviour logp.
- PopArt rescales `critic.value[-1]`; PopArt is NOT a submodule holding the layer (would
  duplicate params in state_dict).
- β is applied from the stage at update time to the whole batch (telescoping needs one β per chain).
- `train_ppo` installs SIGINT/SIGTERM handlers and restores them on exit (tests call it in-process).
- tests/test_ml_train.py's "unimplemented algorithm" test used `algorithm: ppo`; once ppo existed
  it launched a real default-config run into server/runs/ppo_c0. Now uses `ach`.
- bots.arena is imported by train_env/eval_policy for `_tenpai_can_reach_min_faan` and the
  duplicate statistics; that imports the faanbot module but never constructs FaanBot. FaanBot is
  only constructed via `train_env._TEACHERS` when the §10 contingency is enabled.
- Eval is per-hand duplicate (HandEnv seeds), not arena full games: only standalone hands export
  as HandRecord. Points are per hand.
- Worktree: runs/ is gitignored; symlink runs/rl_aux -> main checkout's runs/rl_aux for init_ckpt.

Measured (i7-1265U, 96 envs x 6 workers, 2 torch threads, full-size nets): learner 11.7 s/update
(~356 dec/s), rollout ~2.1k dec/s, end-to-end ~305 dec/s (learner 86%). Env-only 4.0k (C0) /
5.2k (C1) dec/s. C1 exit at 0.3-1B needs a GPU + many cores (cloud); laptop CPU = 11-38 days.
Smoke (15 min from R1 ckpt): win vs tsumogiri 0.03 -> 0.53, C0 exit at ~226k decisions.
Update-60 ckpt vs EfficiencyBot x3 at min_faan 3, 200 sets: +4.47 pts/hand [2.66, 6.28] --
smoke only; not the gate. Launch script: server/runs/ppo_c0_full.sh (worktree, gitignored).
- bots.arena._tenpai_can_reach_min_faan crashed when a seat waited on its own kong's type
  (hand34 counts a kong as 3, so winning_tile_types reports it); fixed by skipping that wait.
- Don't run `--max-minutes` smoke runs concurrently with tests: throughput numbers are CPU-bound.
