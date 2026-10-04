# RL model (R1, 2026-10-02)

Files: `ml/encode_v2.py` (policy/oracle raw rows + batch encoders), `ml/policy_net.py`
(PolicyNet, OracleCritic, Trunk, assemble_logits/logit_source, masked_log_softmax/entropy),
`ml/generate_aux.py` + `ml/aux_data.py` + `ml/aux_train.py` + `ml/aux_eval.py`,
`ml/configs/rl_aux.yaml` (`algorithm: rl_aux` in ml.train), `ml/export.py` NumpyPolicyNet.
Tests: `tests/test_ml_{encode_v2,policy_net,aux,policy_export}.py`. Doc: docs/ml.md §8, §14.

Gotchas:
- Encoder v2 is two-stage: raw uint8 row (from GameState or SeatView) -> `encode_policy_batch`.
  Parity/leak guard is on the raw row only. Single-sample encode ~0.18 ms (numpy overhead);
  batched ~0.02 ms/row total, so the R2 vec env should stack raw rows and encode once per step.
- Claimable-tile plane: set only when the seat holds an offer in the live window. Reference reads
  `discard_pools[turn][-1]` (AWAIT_CLAIMS) or `melds[turn][-1].tile_type` (AWAIT_KONG_ROB):
  `state.turn` stays the discarder/declarer during the window.
- `Flower` is an IntEnum 0..7 and sits in `wall.tiles` next to int TileIds: always
  `isinstance(t, Flower)` before `t // 4`.
- `masked_entropy` must `masked_fill(~mask, 0)` the log-probs: `torch.where` still backprops
  0 * -inf = nan (a test catches it).
- generate_aux with RandomBot full games never ends under min_faan 3 (dealer repeats on draws):
  tests use EfficiencyBot + `--max-hands`.
- FaanBot-mix aux generation: ~600 rows/game, ~0.8 games/s at 10 workers; shanten/ukeire labels
  are about half the cost.
- Forking the generator pool from a process that imported torch warns (C threads); the CLI
  itself only imports numpy, run it with OPENBLAS_NUM_THREADS=1.
- DangerNet comparison: `aux_data.danger_raw` maps v2 rows to v3 rows exactly on own-turn rows
  (tested); `aux_eval.v3_policy_raw` maps v3 rows to v2 with own_flowers unknown (zeros).
- Latency tests (danger and policy) fail under any CPU contention (even a background generator);
  run alone with OPENBLAS_NUM_THREADS=1.
- Worktree-isolated agents can't launch `setsid nohup ... python` (sandbox refuses); the long run
  is a script, `server/runs/r1_full.sh`.
- R1 DONE (2026-10-03). Full run: 10,000 games, 40k steps, best ckpt step 30k. Danger legal-wait
  AUC 0.8705 vs DangerNet 0.8885 (-0.0181, CI [-0.0191,-0.0168]: passes by a hair); hidden-tile NLL
  gain 0.041; deal-in head weak (AUC 0.58). Artifacts: server/runs/rl_aux/{ckpt_best.pt,
  eval_test.json,policy.npz} (gitignored).
- Training doesn't scale past 2 torch threads (0.445 s/step at 2 vs 0.57 at 8); 8 threads on
  this laptop drained the battery even on the 65 W charger and hit 400 MHz power clamps. Use 2.
- Stopping a run: SIGKILL the driver script FIRST (else set -e continues to eval/export on a
  partial ckpt), then SIGTERM the trainer (saves ckpt_last). pgrep -f 'bash runs/...' can match
  the calling shell too: use exact pids. Resume: server/runs/r1_resume.sh (gitignored).
- R1 assessment (docs/ml.md §14 "Reading the results"): danger gap is from no opponent rotation
  + shared trunk, not undertraining; levers = bigger trunk / danger loss weight / distil DangerNet /
  more games. Deferred until R3 shows a defence weakness. Deal-in/win heads are policy-dependent.
