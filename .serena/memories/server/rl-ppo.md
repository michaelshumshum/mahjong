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

## GPU support (branch rl/r2-gpu, 2026-10-03)
- `PPOConfig.device` auto|cpu|cuda (`resolve_device`; explicit cuda without a GPU raises, no
  fallback), `amp` (fp16 autocast + GradScaler, cuda only; scaler saved under learner["scaler"]).
  `ml/check_device.py` = env report + cpu/cuda learner bench + end-to-end throughput.
- CPU path is pinned by `tests/test_ml_ppo_cpu_pin.py` + `tests/pins/ml_ppo_cpu.json` (taken
  before the device change; bitwise identical after). Any new NUMERIC key in metrics records breaks
  it (string keys like device/gpu are filtered). Regenerate only with `--write` for an intended
  behaviour change. `tests/data/` would be gitignored (root `data/` rule): hence `tests/pins/`.
- `Learner.state_dict()` returns CPU tensors; resume uses `map_location="cpu"`;
  `Optimizer.load_state_dict` moves AdamW moments to the params' device (step stays CPU).
- `device_info` initialises CUDA in the parent before `SubprocVecTrainEnv` forks; fine because
  workers never touch CUDA (a forked child can't). Keep workers CUDA-free.
- Locked torch 2.14.0+cu130 has sm_75 SASS (checked `torch.cuda.get_arch_list()` without a GPU);
  needs Windows driver R580+. Fallback cu128 via `uv pip install --reinstall` + `uv run --no-sync`.
- CUDA tests are `-m cuda` + skipif; none have been run (no GPU in dev/cloud). First thing on the
  2060: `uv run --extra ml pytest -q -m cuda tests/test_ml_ppo_device.py`.
- AMP branch was smoke-tested only on CPU by forcing fp16 autocast (metrics within ~1e-3 of fp32).
- Measured this cloud box (4 cores, CPU, 48 envs x 3 workers): learner 20.4 s/update, e2e ~156 dec/s.
- 2060 desktop measured (2026-10-04): CUDA learner 1.43 s/update vs 22.9 s CPU; end to end
  ~1.1-1.5k decisions/s at 10 workers / 160 envs, learner ~55% / rollout ~45%; GPU ~42% busy is
  expected (tiny net, waits on CPU workers). Tests that assert exact equality must pin
  `device: "cpu"` — `auto` picks cuda on a GPU box and cuda isn't bit-reproducible.
