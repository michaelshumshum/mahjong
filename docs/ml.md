# ML

In progress — this doc keeps a plan/status structure (§14 milestones, §15 risks) until the agent
ships.

The learned bot is a self-play RL policy with no dependence on `FaanBot`. It ships as the `T4`
"Expert" tier (`bots/learned.py`, [bots.md §2/§6](bots.md), §14 R4). Two
engine-side pieces came first because retrofitting them later means touching the engine, the
bots, the protocol and every stored record at once: the **action encoding** (§1) and
**persisted `GameRecord`s** (§2).

## 1. Action encoding

A fixed, flat, complete discrete space — every legal action maps to exactly one id, and back:

```
[  0 ..  33]  DISCARD          tile_type t
[ 34 ..  67]  CONCEALED_KONG   tile_type t      (暗槓)
[ 68 .. 101]  ADDED_KONG       tile_type t      (加槓)
        102   PASS                              (decline a claim — and decline a win)
        103   CHOW_LOW         claimed tile is lowest  → use t+1, t+2
        104   CHOW_MIDDLE      claimed tile is middle  → use t-1, t+1
        105   CHOW_HIGH        claimed tile is highest → use t-2, t-1
        106   PUNG
        107   KONG                              (exposed, from a discard)
        108   WIN                               (self-draw or on a discard)
                                                 N_ACTIONS = 109
```

- **Chow is relative** (low/middle/high) — the claimed tile is known from context. Same
  convention as Suphx/Mortal.
- **Kongs are tile-indexed** because you can hold several options at once on your turn.
- **`PASS` covers declining a win**, a real strategic choice under `min_faan`.
- Flower reveal is not an action — it's forced and the engine handles it.
- **`DISCARD` / `CONCEALED_KONG` / `ADDED_KONG` are indexed by `tile_type` (0–33), not physical
  `tile_id`.** This is deliberate, and it has a consequence you need to design around rather than
  discover in a failing test: the protocol's `discard {tile_id}` message and the client's
  animation need physical tile identity (four physical 5s are not interchangeable on screen), but
  the *action space* only ever needs to know which type left the hand — duplicate tiles of the
  same type are fungible to the engine. So `Intent` at the action-space boundary is
  **type-level only** (`tile_type`, never `tile_id`). When the engine applies a type-level
  discard, it removes a physical tile of that type from the hand by a fixed, deterministic rule
  (lowest remaining `tile_id` of that type), and the resulting event carries the physical
  `tile_id` the client animates. The *human* client's WS message still names a physical
  `tile_id`, so a click maps to the right sprite — the server translates that to `tile_type`
  before it ever touches `action_id`/`decode_action`. Bots never see or choose physical `tile_id`
  at all; they only ever produce type-level intents.

Two pure functions in `mahjong_core`, plus one property test — no numpy in the core
([purity](architecture.md)):

```python
def legal_mask(state: GameState, seat: int) -> list[bool]:                 # len 109
def action_id(action: Action, state: GameState) -> int: ...
def decode_action(aid: int, state: GameState, seat: int) -> Action: ...
```

**Built against `GameState`/`Action`, not `SeatView`/`Intent` — permanently, not a stopgap.**
`mahjong_core` must not depend on `app.views` (layering only runs one way, `app` →
`mahjong_core`), so `legal_mask`/`action_id`/`decode_action` stay `GameState`-based even though
`SeatView` (`app/views.py`) exists now. `docs/bots.md §1`'s `Bot.act(view, mask, deadline)`
gets its `mask` from whoever drives the bot calling `legal_mask(state, seat)` against the real
`GameState` it already holds and passing `(view, mask)` to the bot together.

**`action_id` also takes `state`, not just the action.** A `ClaimChow`'s `meld` alone can't say
whether the claimed discard was the run's low/mid/high tile: `Meld.__post_init__` sorts `tiles`
by physical id, which drops which one came from the discard vs. the claimer's own hand once the
`Meld` is built. `state.claim_window.tile` is where that's actually recorded, so encoding a
`ClaimChow` needs it. Every other `Action` variant is self-describing and ignores `state`.

> **Property test:** across every state the self-play harness reaches,
> `action_id(decode_action(aid, state, seat), state) == aid` for every **type-level** legal `aid`
> — both sides of the round trip operate on `tile_type`, never physical `tile_id` (four physical
> 5s collapse to one action id; decoding can't recover which one was meant, because the action
> space was never supposed to know). Also assert every set bit in `legal_mask` decodes to
> something the engine accepts, and the mask is never all-false in an acting phase. **Met** —
> `server/mahjong_core/ml.py`,
> `server/tests/test_ml.py`; states swept from real `RandomBot` self-play games
> (`bots.random`/`engine.reduce`), the same machinery `test_selfplay.py` uses, under `hypothesis`.

The mask comes from the engine, never from the encoder or the network. The heuristic bots use
`legal_mask` too, so a bug in it breaks gameplay immediately instead of poisoning training later.

## 2. Game records

Persisted for every finished game, bot-only included, for replay. Not a training corpus: RL data is on-policy and
regenerated from the pure, seeded engine (§13).

```python
@dataclass(frozen=True)
class GameRecord:
    engine_version: str      # bump on any change to the reducer, wall order, or
                              # flower-replacement ordering
    ruleset: RuleSet         # full body, not a hash — a hash can't be replayed
    seed: int
    actions: list[Action]
    outcome: GameOutcome
```

**Policy:** an `engine_version` bump invalidates replay of every `GameRecord` written under an
older version, and there is no migration path — old records simply stop replaying. Without this
policy stated somewhere, a routine bug fix to the reducer, wall order, or flower-replacement
ordering silently invalidates every stored game and every crash-recovery path, with no way to
detect it after the fact. `ruleset` is the full body rather than `ruleset_hash` for the same
reason: a hash tells you a record doesn't match current rules, but only the full ruleset lets you
actually replay it.

A complete game does not replay from "a few hundred bytes": a 半莊 (four-hand set) runs roughly
600–1,500 actions, and the action log alone is several times that figure in bytes before
considering the ruleset body and outcome. Still cheap to store and cheap to regenerate (pure +
seeded), but size Postgres storage ([infra.md §7](infra.md)) off the real number.

**Implementation note:** the dataclass above isn't materialized separately — the `games` table
row (`server/app/db/models.py`) *is* the persisted `GameRecord`, built by `server/app/db/records.py`'s
`save_game_record(session, state, actions, players=...)` straight from a finished `GameState` (its
`ruleset`/`game_seed`/`seats[*].score`) plus the `Action` log that produced it. `Action` and
`RuleSet` already carry `to_dict`/round-trippable serialization (`RuleSet.to_dict`/`from_dict`,
`actions.action_to_dict`/`action_from_dict`); `outcome` is `mahjong_core.state.GameOutcome`
(`hand_count`, `final_scores`), extracted from a `Phase.GAME_OVER` state by
`mahjong_core.engine.game_outcome`. `engine_version` is `mahjong_core.engine.ENGINE_VERSION`,
stamped by `save_game_record` itself, never caller-supplied. `app/db/records.is_replayable(record)`
implements the policy above as an exact `engine_version` equality check.

**Hand records.** A standalone hand (an RL episode, §7) can't be a `games` row: it stops at
`HAND_OVER` and starts from `engine.new_hand(ruleset, seed, dealer=, prevailing=)`, not hand 1.
It goes to `hand_records` (`HandRecord`: `engine_version`, `ruleset`, `seed`, `dealer`,
`prevailing`, `action_log`, `players`, `result` = outcome/winner/faan/points/per-seat payments/
final scores), via `app/db/records.py`'s `save_hand_record`/`hand_record_columns`; the same
`engine_version` policy applies.

## 3. Why self-play RL

An earlier plan improved `FaanBot` piece by piece: a supervised opponent-danger model inside
`tile_risk`, then a learned evaluator replacing its hand-set weights, then distilling
"`FaanBot` + learned heads" into a network. It was dropped:

| Supervised path, built on `FaanBot` | Self-play RL |
| --- | --- |
| ceiling is `FaanBot` with perfect information (then the `ORACLE` tier, now `OracleFaanBot`), +27.7 points/game over `FaanBot` ([bots §9](bots.md)); learned heads only estimate what it knows exactly | no teacher, so no teacher ceiling: the R3 policy beats `ORACLE` ×3 by +2.88 points/hand [+1.75, +4.01] (§12) |
| claim logic, hand-building and the fold structure stay `FaanBot`'s; a danger model covers defence only, while more than half of that oracle's edge is offence (win rate 0.318 vs 0.152) | learns the whole policy, claims and push/fold included, against the real objective |
| there is no HK equivalent of the Tenhou corpus Suphx/Mortal trained on; cloning the only teacher caps at that teacher | self-play needs no corpus |

The old "RL is out" estimate priced single-sample inference per decision, not the engine:
engine + encode is ~1/15 of one `FaanBot` decision, so with inference batched across envs,
rollout is learner-bound (§13).

The supervised work is kept where RL uses it (§5): the encoder, exact labels, the v3 dataset,
`DangerNet` as trunk template and reference, and the numpy export.

## 4. Reward under `min_faan`

With `min_faan = 3`, **reward is not correlated with shanten**. A speed-maximising policy reaches
tenpai constantly and is then forbidden from winning, because the fast all-sequences hand is
1 faan.

Published mahjong agents are riichi agents, where riichi is itself a declarable yaku and speed
therefore aligns with reward. That advice does not transfer: the objective is hand point delta,
and shanten appears only as annealed potential-based shaping (§9). Keep
`tenpai_rate_on_sub_minimum_hand` in the arena metrics ([bots §7](bots.md)) — it's the
canary for this failure mode in heuristic and learned bots alike.

## 5. Built so far

| Piece | Where | Use in RL |
| --- | --- | --- |
| action space, `legal_mask` | `mahjong_core/ml.py` (§1) | policy output and masking |
| `GameRecord`, `HandRecord` | `app/db/` (§2) | every eval hand exported as a replayable record |
| entitlement-safe view rows | `ml/raw.py` | the one place view-derived columns are built |
| encoder | `ml/encode.py`: `encode_seat_view`, `encode_ruleset`, `encode_batch` | parity target for the fast encoder (§7); ruleset as input |
| exact labels | `bots/labels.py`: `is_tenpai`, `winning_tile_types`, `expected_faan_if_won`, `danger_labels_for_opponents` | auxiliary heads (§8) |
| dataset | `ml/generate_dataset.py`, `ml/pack.py`, `ml/splits.py`, `ml/dataset.py` | optional auxiliary pretraining (§10) |
| `DangerNet` + training | `ml/danger_model.py`, `ml/losses.py`, `ml/train.py`, `ml/configs/danger.yaml` | trunk template and R1 reference (§8, §14) |
| offline eval | `ml/evaluate.py`, `ml/metrics.py` | AUC / log-loss / Brier with game-level bootstrap CIs, reliability table |
| numpy export | `ml/export.py`: `NumpyDangerNet`, `NumpyPolicyNet` (trunk + policy head only), `numpy_trunk`, `masked_log_softmax`; `export_checkpoint` reads R1, `ml.ppo` and league checkpoints and writes provenance into the `.npz` (`__meta__`: source file + sha256, decisions, updates, `engine_version`, `EXPORT_VERSION`; `load_meta`) | torch-free serving, pinned to torch by parity tests |
| single-hand env | `ml/env.py`: `HandEnv`, `encode_obs`, `replay_hand` | the rollout env (§7) |
| vector env | `ml/vec_env.py`: `VecHandEnv` (in-process), `SubprocVecHandEnv` (shared memory) | batched rollout (§7) |
| rollout benchmark | `ml/bench_env.py` | R0 throughput measurement (§13) |
| fast encoder | `ml/fast_encode.py`: `encode_state`, `encode_reference` | policy input from `GameState`, parity-tested (§7) |
| encoder v2 | `ml/encode_v2.py`: `policy_raw` / `policy_raw_from_view`, `encode_policy_batch`, `oracle_raw`, `encode_oracle_batch` | policy and oracle input (§8) |
| `PolicyNet`, oracle critic | `ml/policy_net.py` | the RL model (§8) |
| auxiliary dataset + training | `ml/generate_aux.py`, `ml/aux_data.py`, `ml/aux_train.py`, `ml/aux_eval.py`, `ml/configs/rl_aux.yaml` | aux-head pretraining and the R1 exit measurements (§8, §14) |
| training env | `ml/train_env.py`: `EnvConfig`, `VecTrainEnv`, `SubprocVecTrainEnv`, tsumogiri opponents | PPO rollout (§7) |
| PPO + curriculum | `ml/ppo.py`, `ml/curriculum.py`, `ml/configs/rl_ppo_c0.yaml` | cold start (§9, §10) |
| league | `ml/league.py`, `ml/configs/rl_league.yaml` | C2 opponent pool, personas, learned-only Elo (§11) |
| policy evaluation | `ml/eval_policy.py` | R2 and R3 gates: candidate × 1 vs a `BOT_REGISTRY` bot × 3 (§12) |

`bots/learned.py` (`T4`, [bots.md §2](bots.md)) serves `encode_v2`'s `policy_raw_from_view` and
`NumpyPolicyNet`; nothing else here is wired into a bot.

```
uv run python -m ml.generate_dataset --out data/danger_v3 --games N --parallel 10 \
    --bots FaanBot,FaanBotAggressive,FaanBotDefensive,FaanBotFlushChasing
uv run python -m ml.pack --src data/danger_v3 --out data/danger_v3_packed
uv run python -m ml.train --config ml/configs/danger.yaml [--resume]     # -> runs/danger/
uv run python -m ml.evaluate --ckpt runs/danger/ckpt_best.pt --data data/danger_v3_packed --split test
uv run python -m ml.export --ckpt runs/danger/ckpt_best.pt --out danger.npz
```

**Encoder.** Thermometer planes over the 34 tile types, seats in relative order (self, next,
across, previous), reading only entitled `SeatView` fields — never `view.hands`, the `ORACLE`
tier's omniscient extra ([bots §9](bots.md)). `encode_ruleset` is
`[min_faan, wall_reserve, hand_sets bitmask, effective faan per PATTERNS entry]`: the correct
discard for the same hand depends on the ruleset (Seven Pairs under `hk_casual` vs `hk_classic`/`hk_strict`),
so a network without it overfits one ruleset or gets contradictory labels across several.
Timing/connection fields are not encoded.

**`DangerNet`.** Pre-activation 1-D ResNet with squeeze-excite, 96 channels × 6 blocks (~0.4M
params), tiles on a 37-wide axis with a zero column between suits so kernels never see a false
9m/1p adjacency. Heads per opponent: P(tenpai), P(legal wait on t), P(structural wait on t),
faan class. Trained on v3 (10,674 `hk_classic` games, 5.07M rows) for 36k steps; test split,
1,125 games, at candidate-discard tiles:

| Scorer | legal-wait AUC [95% CI] |
| --- | --- |
| `DangerNet` | 0.889 [0.886, 0.891]; tenpai AUC 0.868 |
| GBDT on `bots/safety.py`'s hand-built signals | 0.853 [0.849, 0.857] |
| `FaanBot`'s `deal_in_probability` | 0.50 (0.66 within tenpai opponents only) |

The baselines were one-off checks and are not kept in code. A 2,000-game held-out set with
`EfficiencyBot` opponents is generated and packed (`data/danger_v3_heldout_eff_packed`) but not
yet scored.

**Dataset rules that must survive into RL tooling:**

- Read melds through `raw.visible_meld_counts34`. Every seat's concealed kongs count there
  ([ADR 0023](decisions/0023-concealed-kong-public.md)); data generated before 2026-10-14 (v3,
  `rl_aux`, and every rollout the shipped policy trained on) hid other seats' concealed-kong tile
  types. v2 data leaked them by accident and is not trained on.
- Seat ↔ bot assignment is shuffled per game (`_shuffled_roster`, its own seeded RNG). A fixed
  assignment let the model read bot identity off dealer/seat-wind context.
- Rows store raw counts (0–4); encoding is a training-time choice, so changing it never means
  regenerating data.
- Splits are game-level (`ml/splits.py`, a pure function of the game seed): rows within a game
  are correlated.
- Process pools use `fork` when the process is single-threaded, the platform default otherwise
  (`ml/mp.py` `mp_context`): 1.8× faster on this workload, and unsafe with other threads alive.

## 6. Goal and constraints

| Requirement | Detail |
| --- | --- |
| Independent of `FaanBot` | not a teacher, reward baseline, feature source, or training opponent |
| `FaanBot` / `OracleFaanBot` | held-out evaluation opponents only; `FaanBot` actions allowed only as the §10 contingency bootstrap |
| Objective | hand point delta — never shanten (§4) |
| `mahjong_core` | stays pure, stdlib-only, the reference implementation; speed-ups ship with equivalence tests and no `ENGINE_VERSION` bump |
| Determinism | a trajectory is a function of `(checkpoint, ruleset, env_seed, policy_seed)`; every eval hand exports a replayable `HandRecord`. GPU training itself is not bit-reproducible. |
| Serving | numpy forward, p99 ≤ 5 ms single-sample CPU incl. encoding, on the target CPU (`make bench-latency`; CI gates ratios, [testing.md §1](testing.md)); fits the existing worker-pool job model, so no batched inference-serving process; torch stays in the `ml` stage, numpy joins base deps |
| Layout | all training code in `server/ml/`; configs in `server/ml/configs/rl_*.yaml` |

## 7. Environment — `ml/env.py`

- **Episode = one hand**, γ = 1. HK has no placement bonus, so per-hand payment is the exact
  objective across a game.
- **Vector env:** worker processes each step K envs into shared-memory buffers; the learner runs
  one batched forward per step. `fork` context per `mp_context` (§5).
- **Self-play over all 4 seats:** every seat's decision is a sample; trajectories are regrouped
  per seat for GAE. Claim-arrival order from a seeded RNG, as `bots/selfplay.py`.
- **Masking:** `legal_mask` only; illegal logits → −∞; entropy over the masked distribution.
  Steps with one legal action are auto-played.
- **Ruleset as input:** `encode_ruleset` already carries `min_faan`, so the curriculum (§10)
  changes the input distribution, not the network. Legal `min_faan` values are `{0, 1, 3, 5}`.
- **Redaction:** policy inputs are built by a fast encoder straight from `GameState`; a parity
  test pins it equal to `encode_seat_view(seat_view(...))` — this is the leak guard.
- No PettingZoo wrapper: the vector env is shaped around batched inference, which the AEC API
  doesn't fit.

### `HandEnv` (built)

```python
env = HandEnv(ruleset, encode=True)
seat, obs, mask = env.reset(env_seed)                 # obs (OBS_DIM,) f32, mask (109,) bool
seat, obs, mask, done, rewards = env.step(action_id)  # rewards (4,) f32, nonzero only at done
env.record(players) -> dict                           # HandRecord columns; replay_hand(record)
```

| Detail | Behaviour |
| --- | --- |
| episode | `new_hand(ruleset, env_seed, dealer, prevailing)` until `HAND_OVER`; `(dealer, prevailing)` = `hand_start(ruleset, env_seed)`, uniform over seats and `prevailing_winds(ruleset)` (East only under `hk_classic`'s `EAST_ONLY`) |
| `seat` | absolute seat to act; -1 once done |
| claim order | `Random(f"claims:{env_seed}")`, independent of any policy RNG seeded with the bare int |
| reward | per-seat score delta / 32 (= `hand_result.payments`); exhaustive draw → all 0 |
| auto-play | a decision with one legal action is applied inside `step`/`reset` and logged, never returned — rare (~1 in 80 random hands) |
| illegal id | `IllegalActionError` (checked against `legal_mask` before `decode_action`) |
| obs | `encode_obs` = `fast_encode.encode_state`, bit-equal to `encode_seat_view(seat_view(...))` flattened; `OBS_DIM` = 1293 under the current pattern registry |
| record | `HandRecord` column dict (§2), persisted with `save_hand_record`; `replay_hand` refuses a different `ENGINE_VERSION` |

### Vector env (built)

```python
venv = VecHandEnv(K, base_seed, ruleset)            # or SubprocVecHandEnv(..., n_workers=W)
seat, obs, mask = venv.reset()                      # (K,), (K, OBS_DIM), (K, 109)
seat, obs, mask, done, rewards = venv.step(actions) # done (K,), rewards (K, 4)
```

| Detail | Behaviour |
| --- | --- |
| seeds | env `i`'s `e`-th episode: `episode_seed(base_seed, i, e)` (blake2b, 63-bit) |
| auto-reset | where `done[i]`, `rewards[i]` is the finished hand's; `seat/obs/mask[i]` already the next hand's |
| buffers | returned arrays are the env's own and overwritten by the next `step` |
| workers | contiguous env slices per process; `RawArray` buffers, pipe carries only commands and finished records (`keep_records`); worker exceptions re-raise in the parent; start method from `ml/mp.py` |
| equivalence | `tests/test_ml_vec_env.py`: in-process vec = K independent `HandEnv`s; subprocess = in-process, bit for bit |

### Training env — `ml/train_env.py` (built, R2)

`VecHandEnv`'s shape, but non-learning seats are played inside the env and each surfaced decision
comes back as one packed `uint8` row, so the learner stacks rows and encodes once per step.

```python
cfg = EnvConfig(ruleset, learners=1, opponent="tsumogiri", aux_rate=0.1)
venv = VecTrainEnv(K, base_seed, cfg)        # or SubprocVecTrainEnv(..., n_workers=W)
buf = venv.reset()                           # buf.seat (K,), buf.mask (K, 109), buf.rows (K, ROW_BYTES)
buf = venv.step(actions)                     # + buf.done, buf.rewards (K, 4), buf.info (K, 5)
venv.configure(cfg2)                         # applies at each env's next episode
```

| Detail | Behaviour |
| --- | --- |
| row (`ROW_FIELDS`, `unpack_rows`) | policy raw row (`encode_v2.policy_raw`) + oracle raw row (all 13 next draws; `k` is applied at encode time) + `cur_shanten` (+1) + `min_faan` + `role` + `aux` flag + `teacher` + `ruleset` (0 = `EnvConfig.ruleset`, else 1 + index into `PRESET_IDS`) + `opponent` (league id, 2 bytes, `opponent_ids`) + auxiliary labels |
| seating | per episode `Random(f"seats:{seed}")` picks `learners` `LEARNER` seats and `frozen` `FROZEN` seats; the rest play `OPPONENTS[opponent]` in-env and never surface |
| `mix` (league) | `(weight, learners, opponent_id)` entries; per episode `Random(f"mix:{seed}")` picks one, which sets `learners` and fills every other seat `FROZEN`; every row of the episode carries the id. Empty (the default) leaves seating as above, same RNG draws |
| `alt_rulesets` | `(preset, probability)` pairs; per episode `Random(f"ruleset:{seed}")` plays that `RULESET_PRESETS` entry as is (its own `min_faan`), else `ruleset`. The learner's `Encoder` builds the ruleset features from the row's `ruleset` + `min_faan` |
| `FROZEN` | surfaced for the caller to act with another policy, never trained on: `ml.ppo.Collector` acts them with the snapshot their `opponent` id names (§11) |
| tsumogiri | own turn: discard the last concealed tile (the draw); claims and kong-rob: `PASS`; never wins, claims or declares a kong |
| auxiliary labels | on `LEARNER` rows with probability `aux_rate` (`Random(f"aux:{seed}")`): opponents' tenpai / waits / legal-win faan and shanten / ukeire after each discard (`ml.generate_aux`'s labellers); win / deal-in / payment and hidden-tile targets are free and filled by the learner for every row |
| `info` | winner, discarder (-1 if none), then seat bitmasks: learners, tenpai at exhaustive draw, sub-minimum tenpai (`bots.arena._tenpai_can_reach_min_faan`) |
| `teacher` | `PAD` unless the §10 contingency is enabled (`EnvConfig.teacher="FaanBot"`); `FaanBot` is only constructed when it is |
| tests | `tests/test_ml_train_env.py`: same seeds → same rows; subprocess = in-process; every surfaced policy row = `policy_raw_from_view(seat_view(...))`; tsumogiri seats never meld or win. `tests/test_ml_league.py`: mix seating and ids on every row, alt-ruleset episodes play and tag the preset |

### Engine speed-ups (in `mahjong_core`, behaviour-neutral)

All built. Engine-only throughput 6.9k → 18.8k decisions/s per core (2.7×, §13).

| Change | Effect |
| --- | --- |
| winning-shape check on type counts: `actions._is_winning_shape` builds one 34-array; standard shape = each suit's 9-count vector in `melds._SUIT_SHAPES` (every complete suit shape, ≤ 4 melds + pair: 21,743 entries, built at import in ~15 ms) + honors in {0, 2, 3} + exactly one pair. Replaces `decompose(...) != ()`, which built and sorted 34 deques per call and was ~60% of engine time. | the bulk of the 2.7× |
| `engine._can_win_with` checks shape on the candidate tuple before copying `SeatState` (3 checks per discard, almost all fail) | ~⅓ of `dataclasses.replace` calls gone |
| table lookup for `tile_id_type` (`tiles._TILE_ID_TYPES`; enum construction was ~15%) | range check kept, same `ValueError` |
| fast encoder writing into a preallocated buffer (`ml/fast_encode.py`) | removes the `SeatView` → numpy hop; encode 0.14 → ~0.02 ms/decision (§13) |

A precomputed table rather than a lazy `functools.cache` (as `shanten.py` uses): fixed memory
(~4 MB) and no per-process growth, where the lazy key space is ~273k suit vectors.

Equivalence, all in the fast suite:

| Test | Proves |
| --- | --- |
| `tests/test_engine_trajectory_pin.py` | sha256 over every action, event, hand result and final `GameState` of seeded games/hands (6 rulesets × uniform-random and greedy min-shanten policies, ~250 wins), committed before any engine change |
| `tests/test_winning_shape.py` | `_SUIT_SHAPES` = `decompose` on all ~273k suit vectors; `_is_winning_shape` = the old `_is_seven_pairs`/`_is_thirteen_orphans`/`decompose` form (hypothesis, near-winning/seven-pairs/orphans/random hands); `_can_win_with` = the old `replace`-then-check form at every turn of seeded hands |
| `tests/test_tiles.py` | `tile_id_type` = `TileType(id // 4)` with the same error on every id in −8..143 |

Remaining profile (engine-only, cProfile): `dataclasses.replace` for state transitions ~20%,
`legal_self_melds`/`legal_claims`/`_chow_options` ~30% together, spread thin. A batched
`tile_id_type` over whole hands was tried and was ~6% slower (list/zip overhead beats the saved
calls on ≤ 14 tiles). Further gains need structural changes (no `replace`, incremental per-seat
type counts) or the escalation below.

Escalation only if the R0 measurement says the env is the bottleneck: compile `mahjong_core`
with mypyc (already `mypy --strict`, zero source divergence) → Rust port behind a differential
test against the Python reference.

## 8. Model — `ml/policy_net.py`

**Encoder v2** (`ml/encode_v2.py`) — seat-centred `encode_seat_view` layout plus: claimable-tile
plane (needed for relative chow ids), last-discard marker, per-seat discard recency, suji.
**Oracle channels** (critic, and the policy during curriculum only): opponents' concealed hands,
wall composition, next-k draws.

Two stages. A **raw row** (dict of uint8 arrays: counts, discard order padded to 32, context,
claim tile) is built by `policy_raw(state, seat)` from `GameState` or by
`policy_raw_from_view(seat_view(...))`; `encode_policy_batch(rows, ruleset_features(r))` turns
stacked rows into tensors. Datasets store raw rows (§5's rule), and the leak guard sits on the
only step that reads state. Cost: raw row ~0.01 ms; tensors ~0.01 ms/row batched at 64, ~0.18 ms
for a single sample.

Policy input — `tiles (70, 34)` + `scalars (80,)` (relative seats: self, next, across, previous):

| Channels | Content |
| --- | --- |
| 0–35 | v1 planes, bit-equal to `encode_state`: own hand (concealed + own melds), 4 seats' visible melds, 4 seats' discards (4-plane thermometers) |
| 36–39 | each seat's last surviving discard (one-hot) |
| 40–51 | each seat's discard recency: age 1–2, 3–5, 6+ discards ago |
| 52 | claimable tile: the live window's tile, only when this seat holds an offer in it |
| 53–55 | suji per opponent (from that opponent's discards) |
| 56 | unseen copies / 4 (a kong counts 3, so it overstates by one) |
| 57–65 | static (suit ×4, rank, terminal), dragon / prevailing-wind / own-seat-wind markers |
| 66–69 | own concealed tiles only (thermometer) |

Scalars: concealed counts /13, turn / dealer / prevailing / seat-wind / phase one-hots, wall /100,
flower counts /8, concealed-kong counts /4, own seat flowers /2, own flower set and season set
/4, then `encode_ruleset` scaled as `encode_batch` scales it (39 + 41).

Oracle input — `(32, 34)`, `encode_oracle_batch(rows, k)`: opponents' concealed tiles (3 × 4
thermometer), opponents' concealed-kong types (3; public since [ADR 0023](decisions/0023-concealed-kong-public.md), kept so the critic's input shape is unchanged), live-wall composition (thermometer, flowers
excluded), next `ORACLE_MAX_DRAWS = 13` front-of-wall draws as one-hot planes (a flower is an
empty plane); planes `k..12` are zeroed, so annealing `k` (§10) keeps the shape.

`tests/test_ml_encode_v2.py`: fast row = reference row on every seat of every state of 40 random
hands (claim-preferring and kong-preferring, so claim windows and concealed kongs occur);
re-dealing opponents' concealed tiles and the wall's tile order leaves the policy tensors
unchanged while the oracle tensor moves; oracle rows account for every hidden tile.

`ml/policy_net.py`:

| Part | Shape |
| --- | --- |
| Policy trunk (`Trunk`) | `DangerNet`'s: stem conv + scalar bias, pre-activation ResNet + SE blocks, 37-wide tile axis; 96 channels × 6 blocks (`PolicyNetConfig`) |
| Policy head | tile-equivariant: 1×1 conv → 3 × 34 (discard / concealed kong / added kong) = ids 0–101; global MLP over [mean, max, scalars, trunk features at the claimable tile] → 7 = ids 102–108 (`assemble_logits`, `logit_source`) |
| Oracle critic (`OracleCritic`) | separate trunk of the same shape over policy + oracle tiles (102 channels) + policy scalars → value; training-only, never served |
| Params | `PolicyNet` 459k (trunk + policy + aux heads); `OracleCritic` 427k |

`masked_log_softmax` sets illegal ids to −∞; `masked_entropy` zeroes them before the product (a
`where` still backprops 0 · −∞ = nan). Tests (`tests/test_ml_policy_net.py`): every legal id of
30 random hands decodes (`mahjong_core.ml.decode_action`) to the action kind and tile type of the
head its logit is taken from.

**Auxiliary heads** (exact labels, weights annealed but never zero), on the policy trunk:

| Head | Output | Label |
| --- | --- | --- |
| per-opponent tenpai / legal wait / structural wait / faan class | `(3,)`, `(3, 34)`, `(3, 34)`, `(3, 34, 10)` | `bots/labels.py` |
| own P(win), P(deal-in), E[payment / 32 \| win] | 3 scalars | hand outcome (`hand_result.payments`) |
| hidden tiles: where each unseen copy is (3 opponents' concealed tiles, live wall; concealed kongs are public) | `(4, 34)` location logits | `GameState` |
| shanten / ukeire after each discard | `(34,)`, `(34,)` | `mahjong_core.shanten`, early curriculum only |

`DangerNet` (§5) is the reference: the trunk's danger head should reach its AUC.

**Auxiliary pretraining** (cwd `server/`):

```
uv run python -m ml.generate_aux --out data/rl_aux --games N --parallel 10
uv run python -m ml.aux_data --src data/rl_aux --out data/rl_aux_packed
uv run python -m ml.train --config ml/configs/rl_aux.yaml               # -> runs/rl_aux/
uv run python -m ml.aux_eval --ckpt runs/rl_aux/ckpt_best.pt --data data/rl_aux_packed \
    --danger-ckpt runs/danger/ckpt_best.pt --split test
```

| Piece | Behaviour |
| --- | --- |
| states | full `hk_classic` games, `FaanBot` weight-profile roster shuffled per game (v3's `_shuffled_roster`); one row per decision with > 1 legal action, every decision type, acting seat's view. Only states: no bot action is a target (§6) |
| row | encoder v2 policy + oracle raw rows; opponents' tenpai / waits / legal-win faan (`bots/labels.py`, `discarder` = the acting seat); shanten + ukeire after each held tile on own discard turns; the hand's outcome for the seat (won, dealt in, payment) |
| storage | `.npz` shards → `ml.aux_data.pack_aux` → one memory-mapped `.npy` per field + game-level `split` (`ml/splits.py`) |
| cost | ~3.5 s per `FaanBot` game (~430 rows); shanten/ukeire labels roughly double `FaanBot`'s own cost |
| training | `algorithm: rl_aux` in `ml.train`: trunk + aux heads only, `ml.losses.aux_loss`; the policy head gets no gradient |
| hidden-tile metric | NLL per unseen copy of its true location vs **uniform over unseen** (P(location) = hidden slots there / all hidden slots, from public counts) |
| danger metric | legal-wait AUC at held tiles on own-turn rows, `DangerNet` scored on the same rows via `aux_data.danger_raw` (the v3 row layout), paired game-bootstrap CI |

## 9. Algorithm — `ml/ppo.py`

- **PPO** with masking, per-seat GAE, PopArt value normalisation, 2 epochs per batch.
- **Asymmetric critic:** V(full state) as baseline from step 0 — unbiased, removes draw-luck
  variance.
- **Oracle dropout:** the policy sees oracle channels early, scaled by a Bernoulli keep mask
  annealed 1 → 0. No oracle-to-blind distillation: a blind student learns the average of a
  teacher whose push/fold depends on hidden hands, which is mistimed.
- **Reward:** own payment / 32 at hand end, zero-sum, unclipped (clipping biases toward cheap
  hands).
- **Shaping:** potential-based only, Φ = −β·shanten with Φ(terminal) = 0; β annealed to 0
  before `min_faan` reaches 3.
- **ACH** (regret-based PPO variant) as an R3 ablation: `policy_loss: ach` (below).

**Built (R2).** `algorithm: ppo` in `ml.train` dispatches to `ml.ppo.train_ppo` with its own
schema (`PPOConfig`); configs are `ml/configs/rl_ppo_*.yaml`.

| Piece | Choice |
| --- | --- |
| update | collect ≥ `batch_size` = 4,096 learner decisions (whole hands; a hand straddling the boundary finishes into the next batch), then 2 epochs × minibatch 512 (16 gradient steps), AdamW lr 3e-4, grad-norm clip 0.5, clip ε 0.2, entropy 0.01, value 0.5 |
| sampling | Gumbel-max over `masked_log_softmax`, numpy `default_rng(seed)`; illegal ids never sampled |
| values | recomputed by the critic for the whole batch at update time (no rollout-time critic forward), so a hand collected under the previous update still gets one consistent set of values |
| GAE | per (hand, seat) chain of that seat's decisions, γ = 1, λ = 0.95, V(terminal) = 0; advantages normalised per batch |
| reward | own payment / 32 at hand end (`HandEnv.rewards`), unclipped, divided in `Learner.update` by the hand's ruleset factor (below) |
| per-ruleset reward scale | `reward_scale_by_ruleset` (preset → divisor, default none = all 1). Each hand's payment reward is divided by its ruleset's factor before shaping, GAE, PopArt and the per-batch advantage normalisation, so alt-preset hands (§10 C2) contribute returns on `hk_classic`'s scale instead of dominating the batch variance. The base ruleset's factor must be exactly 1 (validated), so main-ruleset rewards and PopArt statistics are unchanged by turning it on. Applied at the training boundary (`Learner.train_rewards`), not in the env: `HandEnv`/`TrainEnv` rewards stay payment / 32, batch `points_per_hand` stays raw, and the aux payment head keeps raw labels. Persona rewards (§11) are perturbed first and then scaled, since both are per-hand multipliers. Shaping Φ is in shanten units and is not scaled. Factors are measured constants (§11 has `rl_league.yaml`'s), never an online estimate, so a reward means the same thing for the whole run |
| resume | `--resume` re-reads the YAML for every key the loop reads each update (`entropy_coef`, `clip`, `value_coef`, `grad_clip`, `epochs`, `minibatch`, `batch_size`, `aux_*`, `policy_loss`, `popart_beta`, `total_decisions`, `save_every`, `envs`/`workers`/`threads`/`device`, `reward_scale_by_ruleset`, the whole `league:` config block, and the curriculum's stage specs). Restored from `ckpt_last.pt` instead: model shape (`model_config`), every learner tensor including AdamW's param groups, so **`lr` and `weight_decay` in the YAML are ignored on resume**; schedule state (stage index, rolling window, `held_at`, and the `contingency` block, config fields included); league state (pool, stats, Elo, `next_snapshot`, playable set, RNG); counters and the rollout RNG. `init_ckpt` is never read on resume |
| shaping | Φ(decision) = −β · shanten of the acting seat's hand there (`mahjong_core.shanten`, melds counted, closed-hand forms only when concealed); shaped r_t = Φ(t+1) − Φ(t), Φ(terminal) = 0, so a chain's shaped return is R − Φ(first) (`shaped_rewards`, telescoping test). β is the stage's value at update time, applied to the whole batch so no chain mixes two βs |
| critic | `OracleCritic` over policy tiles + all oracle channels (all 13 draws), initialised from the policy trunk with zero stem weights on the oracle channels; PopArt (EMA β 0.1 per update) on its last layer, loss ½·MSE in normalised units |
| oracle to the policy | `OracleAdapter`: bias-free 3-wide conv from the 32 oracle channels (draw planes `k..12` zeroed) into the trunk's stem, zero-initialised; input × Bernoulli(keep) mask per element, the mask stored per sample (packed bits) so the update replays it. No bias ⇒ keep 0 adds exactly 0 and export drops the adapter |
| blind envs | the first `blind_frac` = 12.5% of envs always run keep 0, k 0: on-policy training data for the blind policy and the blind-win-rate statistic §10 advances on |
| auxiliary losses | `ml.losses.aux_loss` (default `AuxWeights`) on the `aux_rate` = 10% subsample of learner decisions that carry labels; win / deal-in / payment filled from the hand's outcome; coefficient 1.0 → 0.05 linearly over 50M decisions, never 0 |
| init | `PolicyNet` from `init_ckpt` (R1 `runs/rl_aux/ckpt_best_engine130.pt`, i.e. `ckpt_best.pt` migrated to engine 1.3.0: trunk + auxiliary heads; policy head untrained); critic trunk from it as above. A PPO `init_ckpt` (it has a `learner` key, e.g. a C1 hold checkpoint) loads the whole learner instead: policy, critic, adapter, PopArt and AdamW moments, with `lr` / `weight_decay` reset to the config's. Counters (decisions, updates) and the schedule start fresh, so the aux-weight anneal restarts: set `aux_coef_start` to the source run's end value. A resumed run builds its `PolicyNet` from its own checkpoint's `model_config` and never reads `init_ckpt` |
| policy loss | `policy_loss: ppo` (default, the clipped surrogate) or `ach`: ACH's hedge loss (Fu et al. 2022, "Actor-Critic Policy Optimization in a Large-Scale Imperfect-Information Game"), −c·η·y(a)/π_old(a)·A with y the logits centred over legal ids, c = 0 when the ratio is outside [1 − ε, 1 + ε] or y(a) is past ±`ach_logit_threshold` (6) in the advantage's direction; `ach_eta` 1. Entropy, value, aux and the rest of the update are shared. Unit-tested, never trained at scale; the R3 ablation, not yet run, is a separate run with the switch flipped |
| engine migration | `ml.migrate_ckpt SRC DST` carries a PPO or R1 checkpoint from engine 1.0.0 to 1.3.0 ([ADR 0020](decisions/0020-hk-scoring-table-alignment.md)). Only the ruleset block at the end of the scalars changed shape (36 → 30 patterns, `NEW_18` off in `hk_classic`), and within `hk_classic` that block is constant apart from `min_faan`. Each layer reading it (policy/critic `trunk.scalar_proj`, `policy_global.0`, `aux_global.0`, critic `value.0`) gets its pattern columns remapped by rule (座位花→正花, 正花→一台花, 混么九→花么九; new rules zero) and the constant difference folded into its bias, so the migrated network's outputs equal the old ones on `hk_classic` at every `min_faan` (test: ≤ 1e-5; R1 `ckpt_best.pt`: ≤ 1e-6). AdamW moments follow their columns. Rewards still change with the engine: this keeps the starting point, not the training |
| run dir | `meta.json` pins `ENGINE_VERSION` (+ config, resolved device); `ckpt_last.pt` holds models, optimiser, PopArt, schedule state, RNG state, league state (§11, league runs only), all saved on CPU and loaded with `map_location="cpu"`, so a run resumes on either device; resume refuses a different `ENGINE_VERSION`; env seeds restart from `seed·1,000,003 + updates` on resume. SIGINT/SIGTERM save after the current update |
| `metrics.jsonl` | per update: losses, entropy, approx KL, clip fraction, explained variance, PopArt μ/σ, batch win / deal-in / draw / blind-win / sub-min-tenpai rates, stage parameters, rollout and learner decisions/s, resolved device (+ GPU name) |
| device | `device: auto` (CUDA if `torch.cuda.is_available()`, else CPU) \| `cpu` \| `cuda`; explicit `cuda` without a GPU raises at startup, never falls back. Learner (policy, critic, adapter, PopArt, AdamW, every update tensor) and the per-step batched rollout forward on it; envs + encoding stay numpy on CPU, one host→device copy per input per step. Optional `amp: true` (CUDA only): fp16 autocast + `GradScaler`, saved in the checkpoint. Logged to stdout, `meta.json` and each metrics record. Detail and the 2060 setup: §13 |

Tests (`tests/test_ml_ppo.py`; ACH in `tests/test_ml_league.py`: matches its formula, illegal ids and clipped samples get zero gradient, a run trains): GAE against hand-computed λ = 0, ½, 1; shaping telescopes from
every step; PopArt preserves denormalised outputs across updates; masked loss gives illegal ids
zero probability and zero gradient, entropy over legal ids only; with keep 0 the sampled actions
and log-probs are unchanged when every oracle field is rewritten; a toy 3-decision
terminal-reward task goes from ~0.3 to > 0.9 in 150 updates; `train_ppo` runs, resumes, refuses
a mismatched engine and is deterministic for a fixed seed.
`tests/test_ml_ppo_cpu_pin.py` pins a fixed-seed CPU run (metrics + parameter sums) taken before
the device handling landed; `tests/test_ml_ppo_device.py` covers device resolution, CPU-saved
checkpoints, R1 init, and (`-m cuda`, skipped without a GPU) cross-device resume, CPU/GPU
`act` agreement and AMP.

## 10. Curriculum (cold start)

Random play wins ~1–2% of hands even at `min_faan = 0`, so lowering `min_faan` alone is not
enough; hand-building has to be learned first.

| Stage | Opponents | `min_faan` | Oracle to policy | Shaping β | Advance when |
| --- | --- | --- | --- | --- | --- |
| C0 | frozen tsumogiri bots (never claim or win) | 0 | hands + next 13 draws | 1.0 | win rate ≥ 40% |
| C0b | same | 0 | draws k: 13 → 0 | 1.0 → 0.5 | blind win rate ≥ 25% |
| C1 | self-play | 0 → 1 → 3 | keep prob → 0 | 0.5 → 0 | at `min_faan` 3, oracle 0, β 0: win ≥ 15%, sub-min tenpai ≤ 0.32 |
| C2 | league (§11) | 3, 20% other presets | 0 | 0 | R3 gates |

**Contingency:** if C1 is below 10% win rate after 1B decisions, warm-start by cloning
`FaanBot` actions with a KL anchor decayed to 0 within 0.5B decisions; the final agent must
beat the anchor-zero checkpoint (paired CI > 0).

Optional bootstrap that stays within the independence rule: pretrain the trunk's auxiliary
heads on the v3 dataset (§5; states and exact labels only, no actions).

**Built (R2): `ml/curriculum.py`**, selected by a `curriculum:` block in a PPO config
(`ml/configs/rl_ppo_c0.yaml`). Each stage fixes seating and linearly anneals, from its start over
`anneal_decisions`, the draws `k`, the keep probability and β; `min_faan` steps at fractions of
the same anneal. Advancement needs the anneal complete, then a full rolling window (4,000 learner
seat-hands, cleared at anneal completion and at each advance) meeting every threshold.

| Stage | Seating | `min_faan` | `k` | keep | β | Anneal | Advance |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C0 | 1 learner + 3 tsumogiri | 0 | 13 | 1 | 1.0 | — | rolling win ≥ 0.40 |
| C0b | same | 0 | 13 → 0 | 1 | 1.0 → 0.5 | 20M | rolling blind win ≥ 0.25 (blind envs, §9) |
| C1 | 4 learners (self-play) | 0, 1 from ½, 3 at the end | 0 | 1 → 0 | 0.5 → 0 | 200M | win ≥ 0.15 and sub-min tenpai ≤ 0.32 over ≥ 200 tenpai draws |
| C2 | league (§11), `ml/configs/rl_league.yaml` | 3; 10% `hk_casual`, 10% `hk_strict` episodes at their own rules | 0 | 0 | 0 | — | never: the last stage runs until the run's limits; the R3 gates are external (§12, §14) |

C2 runs only when the PPO config has a `league:` block (`Curriculum.league`, set by
`build_schedule`). Without one it stays the R2 stub, so R2 configs behave exactly as before:
`params` raises `NotImplementedError`, `complete()` stops training (the update that advances into
it writes `advanced_to: "C2"`, saves `ckpt_last.pt` and exits; resuming returns at once). The 20%
"other presets" are episode shares (`StageSpec.alt_rulesets` → `EnvConfig.alt_rulesets`, §7).

**`hold_final`** (curriculum key, default `false`). With `true`, meeting the exit criteria of the
last runnable stage (C1 when there is no `league:` block) holds that stage instead of advancing
into the stub; with a league block C1's exit advances into C2 as usual, so training
continues at its end-of-anneal parameters (C1: 4 learners, `min_faan` 3, `k` 0, keep 0, β 0)
until `total_decisions`, `--max-steps`/`--max-minutes` or a signal stops it. It kept the R2 run
training past the C1 exit before the league existed (220.4M → 464.3M decisions,
[rl-learnings.md §2](rl-learnings.md)); league configs don't need it.

| Piece | Behaviour |
| --- | --- |
| exit update | its record carries `held_after: "C1"`; `ckpt_C1_exit.pt` is saved right after it (the exact exit checkpoint, for evaluation) |
| held updates | every record carries `held_at` (decisions at the exit); the rolling window keeps sliding and its `rolling_*` metrics keep being reported; no further advancement |
| state | `held_at` in the schedule state; a state dict without it (pre-`hold_final` checkpoints) loads as not held |
| resumed without the key | a held checkpoint resumed with `hold_final: false` counts as complete and stops |

**C1 thresholds.** With four learners every hand has either one winner or none, so the rolling
per-seat win rate is (1 − draw rate) / 4: the win threshold is really a cap on exhaustive draws,
the passivity canary. Both thresholds are anchored to the `FaanBot` vs `EfficiencyBot` arena
(`docs/bots.md §7`, engine 1.3.0):

| Threshold | Anchor | Value |
| --- | --- | --- |
| win | 0.85 × the arena's average per-seat win, (0.197 + 3 × 0.163) / 4 = 0.172 → 0.146. The 0.85 is the engine-1.0.0 ratio (0.18 / 0.212), kept so the bar didn't move relative to the heuristic table | ≥ 0.15 (draws ≤ 40%; the arena table draws ~31%) |
| sub-min tenpai | `EfficiencyBot`'s rate, the faan-blind baseline: 0.337 (0.324 at engine 1.0.0) | ≤ 0.32, unchanged |

At engine 1.0.0 the win threshold was 0.18 (draws ≤ 28%). Engine 1.3.0 roughly doubled the
arena's draw rate, so 0.18 would have demanded a less drawish table than the heuristic bots
achieve ([ADR 0020](decisions/0020-hk-scoring-table-alignment.md) has the measurements).

Keep and β reach 0 exactly when `min_faan` reaches 3, so the C1 exit is measured blind and
unshaped. How fast each stage actually exited, and what the thresholds do and don't measure in
practice: [rl-learnings.md §2/§6](rl-learnings.md). Contingency (`Contingency`, `enabled: false` by default): if enabled and C1 has run
`after_decisions` (1B) with rolling win < 0.10, the env computes `FaanBot`'s action on every
surfaced decision (`EnvConfig.teacher`) and the loss adds `clone_coef · −log π(a_teacher)` —
cross-entropy to the teacher, i.e. a KL(teacher ‖ π) anchor — decaying linearly from 1.0 to 0 over
`anchor_decisions` (0.5B); then the teacher is switched off and `ckpt_anchor_zero.pt` is saved as
the baseline the final agent must beat. Disabled, `teacher()` is always `None` and the env never
constructs or calls `FaanBot` (`tests/test_ml_curriculum.py`).

## 11. League — `ml/league.py`

| Share | Opponents |
| --- | --- |
| 50% | current policy in all seats |
| 35% | past snapshots (every ~50M decisions, ≤ 32 kept), sampled by win rate against them |
| 15% | reward-perturbed persona snapshots: aggressive (own win ×1.6), defensive (deal-in ×2.0) in `rl_league.yaml` |

Heuristic bots never enter the pool, so evaluation against them stays held out. Track the
exhaustive-draw rate as the passivity/collusion canary.

**Built (R3): `ml/league.py`**, played by curriculum stage C2 (§10) when the PPO config has a
`league:` block (`LeagueConfig`; `ml/configs/rl_league.yaml` holds the defaults).

| Piece | Behaviour |
| --- | --- |
| shares | per **episode** (table), from `League.mix()` → `EnvConfig.mix` (§7): `self_share` 4 `LEARNER` seats; `past_share` / `persona_share` `seat_learners` (1) learner seats + the rest `FROZEN`, all one snapshot. A share whose pool is empty goes to self-play. With 1 learner seat, learner samples split ~80 / 14 / 6 (a 1-v-3 hand surfaces a quarter of its decisions to the learner) |
| `FROZEN` seats | acted by the snapshot's own `PolicyNet` (Gumbel-max sampling, no oracle), never kept as samples; `Collector` encodes the step once and runs one forward for the learner rows plus one per distinct opponent present |
| playable set | `active_past` (3) past + `active_personas` (1) persona draws, with replacement, redrawn every `rotate_every` (16) updates and right after a snapshot: bounds the forwards per step at 5. An evicted snapshot stays playable for 64 updates so hands in flight finish with it |
| past snapshots | `snapshot_every` (50M) learner decisions, the first when the league starts (so a run entering C2 has an opponent at once); `max_past` (32), oldest evicted |
| PFSP | weight (1 − p)^`pfsp_power` (2), p = the learner's share against the snapshot under `pfsp_metric`. `win` (the dataclass default): p = x, the pairwise win share: per hand, each (learner seat, snapshot seat) pair scores 1 / ½ / 0 by payment, so x = ½ at parity under any seating; ½ prior (one pseudo-game). `points` (`rl_league.yaml`): p = σ(d / `points_scale`), d = the mean learner-minus-snapshot payment per (learner seat, snapshot seat) pair, 0 prior (one pseudo-pair). Counts decay × `stat_decay` (0.999) per update (time constant ~1,000 updates ≈ 4M decisions) |
| why points | x counts a 1-faan and a 10-faan win alike. The C2 run drifted to "win less often, win bigger": x sat at ~0.48 against equal-strength snapshots while the points didn't move, so PFSP was effectively uniform and Elo read the style change as a strength loss. d is the quantity the learner is trained on |
| `points_scale` | 0.83 reward units: the Gaussian-equivalent mapping. With per-seat payment SD σ ≈ 0.87 (`hk_classic`, and every preset once rewards are scaled, §9) and exchangeable zero-sum seats (correlation −⅓), one pair's difference has SD σ·√(8/3) ≈ 1.42; Φ(d / 1.42) is the win share a Gaussian difference with mean d would give, and σ(1.702·z) ≈ Φ(z) gives 1.42 / 1.702 ≈ 0.83. So p and x are on the same scale at parity and Elo stays comparable. Near parity p is still ≈ ½ (a 0.05-unit edge is p ≈ 0.515): sharpness is `pfsp_power`'s job, not the metric's |
| alt-preset reward scale | `rl_league.yaml` sets `reward_scale_by_ruleset` (§9): `hk_classic` 1, `hk_casual` 4.14, `hk_strict` 1.13, each the preset's per-hand payment SD over `hk_classic`'s, measured on the C2 run's policy in reward units: 0.87 (`hk_classic`), 0.98 (`hk_strict`), 3.6 (`hk_casual`: full-spicy table, 13-faan cap, max 48). Unscaled, the 10% `hk_casual` hands supplied ~65% of the return variance: the per-batch advantage normalisation shrank the `hk_classic` signal against the fixed entropy bonus, and since the league started PopArt σ rose 0.6 → 1.4–2.0 (spikes 4–6), explained variance fell 0.28 → 0.13–0.17 and entropy rose 0.77 → 0.9. Constants, not an online estimate: a scoring-table derivation would need the policy's faan distribution anyway, and a moving divisor would move the reward |
| units | `observe` gets `Learner.train_rewards`: payment / 32 divided by the hand's ruleset factor (§9), so an alt-preset hand weighs what it weighs in training and the `hk_casual` tail can't swamp d. x is invariant to the factor (both seats of a hand share it) |
| personas | at every past snapshot, each persona is a fork of the learner (policy, critic, PopArt, AdamW) trained `persona_updates` updates of 4-seat self-play on its perturbed reward (`persona_rewards`: the winner's payment × `win`, the discarder's on a discard win × `deal_in`, then the per-ruleset scale, §9) in its own envs and RNG streams, then frozen. `max_personas` (8), oldest evicted. Dataclass defaults: 100 updates, ×1.3 / ×1.5. `rl_league.yaml`: 400 updates (~1.6M decisions each), aggressive `win` 1.6, defensive `deal_in` 2.0 |
| persona strength | at 100 updates and ×1.3 / ×1.5 a persona's KL from its parent was 0.06–0.15 nats, top-1 agreement 0.81–0.85: less than ordinary training drift between checkpoints 2M decisions apart, so the persona share was more past-snapshot play. Hence 4× the updates and stronger multipliers |
| persona cost | measured on the 2060 box: 565 s per fork at 100 updates (snapshot + 2 personas, ~1.45k persona decisions/s; venv startup is a few seconds), ~2,170 s (~36 min) at 400. Between forks, 50M decisions at the league's ~1.1k/s ≈ 12 h, so the fork share went ~1.3% → ~5%. New persona settings take effect at the next fork (`next_snapshot` is league state) |
| Elo | learned-only (§12): each past snapshot is anchored at the learner's rating when taken (the first at 0); the learner's rating is the maximum-likelihood fit (bisection) of its share p against them, weighted by the decayed count (games for `win`, pairs for `points`) plus the one-pseudo-count prior. Cheap: one 1-D solve per update |
| state | `League.state_dict()` in `ckpt_last.pt` (`league` key, only in league runs): every snapshot's weights (CPU, ~1.8 MB each at 96 × 6), stats, Elo anchors, next snapshot, the playable set and the league RNG. Non-league checkpoints are unchanged; `--resume` rebuilds the pool on the run's device. The `league:` config block is re-read from the YAML on resume (§9), the state above is not |
| pre-points state | entries saved before `points`/`pairs` existed load with both at 0, i.e. at the prior (d = 0, p = ½). They aren't seeded from x: x is the frequency signal the points metric replaces. Under `points`, PFSP is uniform and the Elo holds at its saved value until evidence accrues; d reaches ~63% of its steady weight after ~1,000 updates (4M decisions) |

Metrics, every C2 record in `metrics.jsonl`:

| Key | Meaning |
| --- | --- |
| `league_past`, `league_personas` | pool sizes |
| `league_mix_self` / `_past` / `_persona` | share of this batch's finished hands by opponent type |
| `league_draw_self` / `_past` / `_persona` | exhaustive-draw rate per type; `league_draw_self` is the collusion canary (4 copies of one policy), next to `batch_draw_rate` |
| `league_vs` | per snapshot (`past<id>` / `<persona><id>`): pairwise win share `x`, mean pair points difference `pts` (training reward units), the PFSP/Elo share `p` under `pfsp_metric`, learner seat-hand win rate, decayed hands, Elo anchor, decisions when taken |
| `league_pts_past`, `league_pts_persona` | pair-weighted mean points difference over that pool (no prior), once it has any |
| `league_elo`, `league_active` | learner's Elo, the playable ids |
| `league_snapshot`, `league_snapshot_s` | on a snapshot update: the new past id, seconds spent (persona forks included) |

Tests (`tests/test_ml_league.py`): persona reward scaling; pairwise scores ½ at parity; pairwise
points; PFSP weights and the sampled frequencies; the points metric ranking a "win big, rarely"
snapshot the opposite way to x; points Elo and metrics; a pre-points state loading at the prior; mix shares with empty pools; rotation cadence; snapshot
cadence and both caps; snapshots are copies; evicted snapshots stay playable; win share, mix,
draw and Elo bookkeeping; state round trip (same models, same next draws); `FROZEN` seats act
with their snapshot and never become samples; C2 runs only with a league and never advances;
`hold_final` advances into C2 once a league exists; a league run from a PPO `init_ckpt` (first
snapshot = the checkpoint's policy, critic / PopArt / AdamW carried, `lr` reset) snapshots,
forks personas and resumes; a league block outside C2 changes nothing; a CPU smoke run of
`rl_league.yaml` with subprocess envs.

**Rollout cost (measured, CPU).** `Collector.collect`, full-size nets (96 × 6) for the learner
and 4 playable snapshots, 48 envs × 3 workers, torch 1 thread, `min_faan` 3 + alt presets,
4 batches of 4,096 after warm-up; 4-vCPU Xeon @ 2.1 GHz (a cloud container, not the 2060 box):

| Seating | Learner decisions/s | Env rows/s | Rows per learner decision | ms/step |
| --- | --- | --- | --- | --- |
| C1 self-play (4 learners) | 991 | 945 | 0.95 | 50.8 |
| league, `seat_learners` 1 (default) | 584 (0.59×) | 881 | 1.51 | 54.5 |
| league, `seat_learners` 2 | 678 (0.72×) | 831 | 1.23 | 57.8 |

Per surfaced row the league costs ~7% (the extra forwards); the rest of the slowdown is
structural: a `FROZEN` row is an env step and a forward that yields no sample. On the 2060 box
the C2 run measured ~1.1k learner decisions/s end to end (rollout 2.17 s + update 1.50 s per
batch) against the C1 hold's ~1.6k/s: 0.7×, in line with the CPU ratio
([rl-learnings.md §1](rl-learnings.md)). `seat_learners: 2` is the lever if that is too slow (it
mixes some self-play into the snapshot tables). Further lever: one batched forward over stacked
snapshot weights (`torch.func.functional_call` + `vmap`).

Launch from a C1 hold checkpoint (cwd `server/`; copy it to `runs/ppo_c1/ckpt_last.pt` or edit
`init_ckpt`):

```
mkdir -p runs/ppo_league
OPENBLAS_NUM_THREADS=1 uv run --extra ml python -m ml.train --config ml/configs/rl_league.yaml \
    [--resume] 2>&1 | tee -a runs/ppo_league/train.log
```

## 12. Evaluation

- **Gate:** paired-duplicate CI ([bots §7](bots.md)), candidate × 1 vs `FaanBot` × 3,
  on fresh seeds (tune and gate on different seed sets — picking the best of k configs on the
  gate seeds is a winner's curse), plus a bootstrap CI, since `arena.py`'s CI is a normal
  approximation over heavy-tailed payouts. Also vs `OracleFaanBot` (the `ORACLE` tier until [ADR 0022](decisions/0022-oracle-learned-tier.md); a defence probe, not a ceiling: the agent already outscores it, [rl-learnings.md §4](rl-learnings.md)) and
  mixed tables: `EfficiencyBot` and the `FaanBot` weight profiles (`bots/faanbot.py`
  `WeightProfile`, registered in `BOT_REGISTRY` as `FaanBotAggressive`/`FaanBotDefensive`/
  `FaanBotFlushChasing`).
- **Metrics:** points/game, win, deal-in, avg winning faan, tenpai-at-draw,
  `tenpai_rate_on_sub_minimum_hand`, exhaustive-draw rate, exploiter gain, agreement with
  `FaanBot` (reported, not gated).
- **Sample size:** SD per duplicate set is ~16–19 points/game (from the existing arena CIs).
  For 80% power: δ = 5 → ~110 sets, δ = 2 → ~700, δ = 1 → ~2,800.
- **During training:** learned-only duplicate matches against league snapshots (Elo); `FaanBot`
  gates only at milestones. Built as the league's own Elo (§11): fit from the C2 training hands
  against past snapshots (pairwise by payment), not from separate duplicate matches, so it costs
  nothing extra but is noisier and on-policy (the learner samples, it doesn't argmax).

**Built (R2): `ml/eval_policy.py`** — the R2 gate harness, candidate × 1 vs a `BOT_REGISTRY` bot
× 3 (default `EfficiencyBot`). The shipped bot is `BOT_REGISTRY["LearnedBot"]`, so
`--candidate-bot LearnedBot` gates the production path (§14 R4).

```
uv run python -m ml.eval_policy --ckpt runs/ppo_c0/ckpt_last.pt --sets 700 --seed 1000000 \
    --parallel 6 --out eval.json --records eval_hands.jsonl
```

| Detail | Behaviour |
| --- | --- |
| duplicate set | one `HandEnv` episode seed (dealer / prevailing from `hand_start`), played 4 times with the candidate in each seat; points per hand, not per game, since an RL episode is a hand and only standalone hands export as `HandRecord`s |
| candidate | `PolicyBot`: `policy_raw_from_view(seat_view(...))` → `PolicyNet` → masked argmax (or seeded sampling); no oracle path exists here. `--candidate-bot NAME` seats a `BOT_REGISTRY` bot instead (a heuristic for calibration, the shipped `LearnedBot`, or an `OMNISCIENT_BOTS` one such as `ORACLE`, served through `_view_for` like an opponent; the report's `candidate_omniscient` says which) |
| opponents | any `BOT_REGISTRY` name, `ORACLE` included: every `BOT_REGISTRY` seat gets its view from `bots.arena._view_for` (the sanctioned omniscient call site, [bots.md §9](bots.md)), so only `OMNISCIENT_BOTS` names see `.hands`; a `PolicyBot` seat always gets a plain `seat_view` (`tests/test_ml_eval_policy.py` spies on every view served) |
| statistics | each played hand is a one-hand `bots.arena.GameRecord`, so `_collect_stats`, `_paired_differences` (candidate − mean of the other three) and the normal CI are `bots.arena`'s; plus a seeded percentile bootstrap CI |
| metrics | per side: points/hand, win, deal-in, avg winning faan, tenpai-at-draw, `tenpai_rate_on_sub_minimum_hand`; table exhaustive-draw rate |
| records | every hand as `HandRecord` columns (`--records`, JSON lines; `players` names the candidate's seat), replayable with `ml.env.replay_hand` |
| checkpoints | `ml.ppo` (`learner.policy`) or R1 `rl_aux` (`model`) |

**Calibration (2026-10-04, engine 1.0.0: predates ADR 0020).** Heuristic bots substituted as the candidate, hk_classic, 200 sets,
points per hand:

| Candidate vs opponents × 3 | Paired diff [95% CI] | Reading |
| --- | --- | --- |
| `FaanBot` vs `EfficiencyBot` | −0.09 [−1.21, +1.04] | consistent with the per-game arena (+0.59/game ≈ +0.15/hand, CI spanning 0) |
| `RandomBot` vs `EfficiencyBot` | −5.91 [−6.55, −5.27] | negative control |
| `EfficiencyBot` vs `FaanBot` | −1.86 [−3.09, −0.63] | 1-vs-3 is not antisymmetric: it measures play against a table of the other bot |
| R2 smoke checkpoint (309k decisions) vs `EfficiencyBot`, fresh seeds | +4.89 [+3.03, +6.76] | reproduces the +4.47 from the smoke run's seeds |
| same, vs `FaanBot` | +4.51 [+2.42, +6.61] | win 0.236 vs 0.191, avg winning faan 4.85 vs 4.12, sub-min tenpai 0.12 vs 0.18; deals in more (0.168 vs 0.133) |

Leak check on the evaluation path: 19,095 permutations of every tile id the candidate can't see
(opponents' concealed hands + live wall) left `policy_raw_from_view(seat_view(...))` unchanged in
all cases. So the harness is unbiased at this resolution and the early edge over both heuristic
bots is real at 200 sets — the heuristic bots are weak at hk_classic rather than the policy
being strong. The R2/R3 gates still need ≥ 700 / ≥ 1,000 fresh sets.

## 13. Data and compute

On-policy, transient. Kept: checkpoints (league ≤ 32 + gate winners), every eval `HandRecord`,
`metrics.jsonl`, and a 1% raw-count trajectory sample (rolling cap) for debugging. Run metadata
pins `ENGINE_VERSION`; the env refuses to start on a mismatch.

| Setup (`hk_classic`, per core) | Per decision |
| --- | --- |
| engine + `RandomBot` ×4 | ~0.15 ms |
| engine + `FaanBot` ×4 | ~4.6 ms (~1.6 s, ~350 decisions per game) |

`FaanBot` is ~97% of that cost; engine + encode is ~1/15 of one `FaanBot` decision. Rollout
workers are CPU, the learner needs a GPU. Sustained multi-hour runs on laptop-class hardware
throttle, so budget in core-hours, not wall-clock.

**Measured (R0, `ml/bench_env.py`)** — `hk_classic`, i7-1265U laptop (12 threads: 2 P-cores +
8 E-cores), masked uniform-random actions, 1,000 steps per env. `+ encode` adds the observation
per decision and a dummy batched numpy linear policy (forward ≤ 0.01 ms/decision of the totals).
Reference encoder = `encode_seat_view(seat_view(...))`, measured before `encode_obs` switched to
`ml/fast_encode.py`; the CLI now measures the fast one.

```
uv run python -m ml.bench_env --envs 64 --steps 1000 [--workers W]
```

Before the §7 engine speed-ups:

| Envs × workers | engine only | + reference encode + forward | + fast encode + forward |
| --- | --- | --- | --- |
| 64, in-process | 7.2k decisions/s (0.139 ms) | 3.6k/s (0.275 ms) | 6.4k/s (0.156 ms) |
| 64 × 4 | 14.5k/s | 6.7k/s | 11.6k/s |
| 128 × 8 | 22.5k/s | 10.6k/s | 17.8k/s |
| 120 × 10 | 24.5k/s | 11.3k/s | 18.2k/s |

After them (same seeds and machine; before/after interleaved, best of 2; the pre-speed-up tree
re-measured alongside at 6.9k / 14.3k / 22.0k / 23.2k engine-only, 6.1k / 11.2k / 16.5k / 17.6k
with fast encode, so the rows above are 3–5% optimistic against this run):

| Envs × workers | engine only | + fast encode + forward |
| --- | --- | --- |
| 64, in-process | 18.8k decisions/s (0.053 ms) | 13.9k/s (0.072 ms) |
| 64 × 4 | 33.7k/s | 20.7k/s |
| 128 × 8 | 56.5k/s | 30.3k/s |
| 120 × 10 | 62.5k/s | 32.1k/s |

- Per core, engine + encode was 0.275 ms with the reference encoder ≈ 1/17 of a `FaanBot`
  decision (4.6 ms), in line with the ~1/15 estimate; now 0.072 ms ≈ 1/64.
- Engine-only 2.7× in-process; with fast encode + forward 2.3× in-process, 1.8× at 10 workers.
  Encode + forward (~0.02 ms) is now ~¼ of per-decision time.
- At ~32k decisions/s, 1B decisions is ~9 h on this laptop before throttling.
- Scaling past 4 workers is sub-linear (E-cores), flatter still with encoding (20.7k at 4
  workers → 32.1k at 10).
- Pin the learner process's BLAS threads (`bench_env` sets `OPENBLAS_NUM_THREADS=1`): idle
  OpenBLAS threads spin and cut env-worker throughput ~3× (reference encoder, 64 × 4: 6.6k vs
  2.2k decisions/s). Torch's intra-op threads in the learner need the same treatment.

Budget, in decisions (1B ≈ 11M hands; pre-R2 estimates, ±3×): C0–C1 0.3–1B, beating `FaanBot`
2–5B. Actual: C1 exited at 220.4M, about the curriculum's minimum (C0b anneal 20M + C1 anneal
200M); the policy was ahead of `FaanBot` (paired CI > 0) from 98.6M and at +8–9 points/hand from
230.9M ([rl-learnings.md §2, §4](rl-learnings.md)).

PPO on the laptop's CPU is learner-bound at ~305 decisions/s end to end; the measurement and the
cloud-box plan it led to are in [ADR 0021](decisions/0021-rl-training-hardware.md). Training runs
on the 2060 desktop below.

### GPU path (R2)

`device` in the PPO config (§9): `auto` (default; CUDA if `torch.cuda.is_available()`, else CPU),
`cpu`, `cuda`. Explicit `cuda` without a GPU raises at startup.

| Piece | Where it runs |
| --- | --- |
| envs, engine, encoding (`policy_raw`/`oracle_raw`, `encode_*_batch`), GAE, sampling (Gumbel-max, numpy RNG) | CPU, numpy; env workers are processes |
| rollout forward (one batched `PolicyNet` + `OracleAdapter` call per env step) | `device`; inputs copied host→device once per step, log-probs back once |
| learner: policy, `OracleCritic`, `OracleAdapter`, PopArt, AdamW, every update tensor | `device` |
| checkpoints | saved on CPU (`Learner.state_dict`), loaded with `map_location="cpu"`; a GPU-written run resumes on CPU and vice versa; AdamW moments move with `Optimizer.load_state_dict`; R1 `ckpt_best.pt` and pre-GPU PPO checkpoints load unchanged |
| `eval_policy` / `load_candidate`, serving | CPU only, `map_location="cpu"` |
| AMP | `amp: true`, CUDA only, off by default: fp16 autocast + `GradScaler` (Turing has fp16 tensor cores, no bf16); losses, PopArt and the softmax stay fp32 |

| Rule | Why |
| --- | --- |
| `torch.set_num_threads(threads)` (2) on both devices | on CUDA host threads only launch kernels; more of them contend with env workers for cores |
| `OPENBLAS_NUM_THREADS=1` (set in `ml/ppo.py` before numpy loads) | idle BLAS threads spin and starve env workers (above) |
| CPU path unchanged | `device: cpu` reproduces the pre-GPU run exactly (`tests/test_ml_ppo_cpu_pin.py`) |
| GPU not bit-reproducible | cuDNN/cuBLAS kernel choice and atomics; seeds still fix envs and sampling RNGs (§6) |
| no pinned host memory | per-step input is ~1–2 MB; `check_device` measures pageable vs pinned for the user to decide, and pinned memory is capped under WSL2 (NVIDIA's WSL guide, "Known Limitations") |
| env workers never touch CUDA | they fork from a parent that has initialised CUDA (device check); a forked child can't use CUDA, and doesn't need to |

**Measured on the 2060 desktop (RTX 2060 6 GB + i5-10400F, 6 cores / 12 threads, WSL2,
driver 610.88), 2026-10-04.** `check_device`, C0 config, CUDA end to end:

| Workers / envs | Rollout/s | Learner/s | End to end/s | Learner share |
| --- | --- | --- | --- | --- |
| 6 / 96 | 1.7–1.9k | 1.9–2.9k | 0.9–1.2k | 0.41–0.48 |
| 8 / 128 | 2.4k | 2.1k | 1.1k | 0.53 |
| **10 / 160 (chosen)** | 2.6–2.7k | 2.1k | 1.1–1.2k | 0.55 |
| 12 / 192 | 2.8k | 2.1k | 1.2k | 0.56 |

| Finding | Value |
| --- | --- |
| learner update, full-size nets, batch 4,096 | CPU 22.9 s vs CUDA 1.43 s (16×); peak GPU memory 0.79 GB |
| bottleneck | neither: learner ~55% of wall time, rollout ~45%; 12 workers only ~3% over 10 |
| torch threads | 2 and 4 equal (~1.14–1.19k/s); keep 2 |
| amp | 1.88 vs 2.11 s/update, 1.18k vs 1.12k/s end to end: within run-to-run noise, off |
| live C0b run | ~1.5k decisions/s (C0b steps faster than C0); ~5.4M decisions/h |
| GPU utilisation | ~42% mean, sawtoothing 6–85% between rollout (waits on CPU workers) and update phases; a ~1M-param net can't saturate a 2060. Windows Task Manager shows CUDA work only on the *Cuda*/*Compute_0* engine graph |

The full runs: R2 1.1–1.7k decisions/s (1.58–1.65k through the C1 hold), R3's league ~1.1k/s
([rl-learnings.md §1](rl-learnings.md)). Remaining speed levers are CPU-side (engine, rollout-loop
overhead, cores), not the GPU.

Rollout and update alternate (no overlap), so end-to-end ≈ 1 / (1/rollout + 1/learner).

**`ml/check_device.py`** — run on the target machine before a long run:

```
uv run --extra ml python -m ml.check_device                       # cpu + cuda, config defaults
uv run --extra ml python -m ml.check_device --workers 10 --envs 160 --updates 5 --json dev.json
uv run --extra ml python -m ml.check_device --amp                 # fp16 on cuda legs only
```

| Section | Reports |
| --- | --- |
| environment | torch / CUDA / cuDNN versions, `cuda.is_available()`, driver (`nvidia-smi`, falling back to WSL's `/usr/lib/wsl/lib/nvidia-smi`), GPU name, capability, memory, whether the wheel's arch list has kernels for it |
| learner | one real C0 batch, full-size nets: s/update and learner decisions/s per device, rollout-forward ms/step, peak GPU memory |
| transfer | one step's input host→device, pageable vs pinned |
| end to end | `train_ppo` for `--updates` updates per device (first update excluded): rollout / learner / total decisions/s, updates/s, learner share |

### Torch build for the RTX 2060 (Turing, sm_75)

`uv.lock` pins `torch 2.14.0` from PyPI, whose Linux x86-64 wheel is the CUDA 13.0 build
(`+cu130`). **It supports the 2060; no lockfile change.**

| Check | Result |
| --- | --- |
| kernels for sm_75 | `torch.cuda.get_arch_list()` of the locked wheel: `sm_75, sm_80, sm_86, sm_90, sm_100, sm_120`. CUDA 13 dropped Maxwell/Pascal/Volta (sm_50–sm_70); Turing is its oldest supported architecture |
| driver | CUDA 13.0 needs an R580+ driver (≥ 580.65.06 for 13.0 GA; minor-version compatibility ≥ 580). Under WSL2 that is the **Windows** GeForce driver |
| risk | Turing is CUDA 13's minimum: a future CUDA major (and the torch wheels on it) may drop sm_75. Pin torch below that release if it happens |
| fallback, driver stuck below 580 | a cu128 build of the same torch (needs R570+), installed over the synced env, then run with `--no-sync` so `uv run` does not reinstall the locked wheel: `uv pip install --reinstall "torch==2.14.0" --index-url https://download.pytorch.org/whl/cu128` then `uv run --no-sync python -m ml.check_device`. The lockfile and the laptop install stay as they are |

Sources: NVIDIA CUDA 13.0 toolkit release notes (driver table, dropped architectures),
docs.nvidia.com/cuda/archive/13.0.0/cuda-toolkit-release-notes/; PyTorch dev-discuss "CUDA 12.6
wheels will no longer be published from PyTorch 2.15" (cu13 builds cover Turing → Blackwell);
NVIDIA CUDA on WSL user guide, docs.nvidia.com/cuda/wsl-user-guide/.

### WSL2 setup (2060 desktop)

| Step | Detail |
| --- | --- |
| driver | install only the Windows NVIDIA GeForce driver (R580+). Never install a Linux NVIDIA driver inside WSL: the Windows driver exposes `libcuda` to WSL at `/usr/lib/wsl/lib`, and a Linux driver overwrites it. No CUDA toolkit needed (the wheel bundles its runtime) |
| filesystem | clone the repo inside WSL's ext4 (`~/mahjong`), never under `/mnt/c`: Windows-drive access from WSL goes over 9P and is far slower for the many small files Python imports |
| `.wslconfig` | `%UserProfile%\.wslconfig`, then `wsl --shutdown`; see below |
| deps | `cd server && uv sync --extra ml` (the locked cu130 wheel, see above) |
| verify | `nvidia-smi` inside WSL shows the 2060 and driver ≥ 580; then `uv run --extra ml python -m ml.check_device` shows `cuda_available: true`, `wheel_has_kernels: true` |
| sleep | Windows: Settings → Power → Screen and sleep → "Never" on AC, or `powercfg /change standby-timeout-ac 0` and `powercfg /change hibernate-timeout-ac 0`. A sleeping host suspends the WSL VM mid-run |
| launch | inside `tmux` (closing the terminal must not kill the run), from `server/`, see below |

```ini
# %UserProfile%\.wslconfig
[wsl2]
# all 12 threads: env workers are the bottleneck
processors=12
# ~75% of host RAM; leave Windows the rest
memory=12GB
swap=8GB
```

```
cd ~/mahjong/server && mkdir -p runs/ppo_c0
OPENBLAS_NUM_THREADS=1 uv run --extra ml python -m ml.train --config ml/configs/rl_ppo_c0.yaml \
    [--resume] 2>&1 | tee -a runs/ppo_c0/train.log
```

`device: auto` picks the GPU; the first stdout line is the resolved device. Set `workers` / `envs`
in the config to what `check_device` measured best (6 → 10 workers; hyperthreads add less than
cores). `runs/rl_aux/ckpt_best.pt` (R1) has to be copied over for `init_ckpt`; checkpoints move
between the laptop and the desktop in either direction.

## 14. Milestones

| # | Deliverable | Exit criteria |
| --- | --- | --- |
| R0 env | engine speed-ups + equivalence tests; `ml/env.py`; fast encoder; `HandRecord` export | end-to-end rollout with batched inference measured and recorded here; encoder parity test; same seed → same trajectory; env games replay via `reduce` |
| R1 model | encoder v2; `PolicyNet` + oracle critic + auxiliary heads; numpy export with parity test | p99 ≤ 5 ms incl. encode (slow-marked test); danger head within 0.02 AUC of `DangerNet`; hidden-tile head beats uniform-over-unseen |
| R2 cold start | `ml/ppo.py`, `ml/curriculum.py`, `configs/rl_*.yaml` | C1 exit (§10); paired CI > 0 vs `EfficiencyBot` |
| R3 league | `ml/league.py`, personas, ACH ablation | paired CI > 0 vs `FaanBot` on ≥ 1,000 fresh sets; not worse on mixed tables; sub-min tenpai not worse. Stretch: ≥ +5 points/game (measured per hand, §12) |
| R4 ship | `bots/learned.py` `LearnedBot` in `BOT_REGISTRY`; numpy in base deps; weights artifact; "Expert" difficulty | R3 gate re-run on fresh seeds; p99 ≤ 5 ms on the server CPU; bot load not regressed |

R0 progress: **done** — `ml/env.py`, `ml/vec_env.py` (in-process + shared-memory workers), `HandRecord` export + `replay_hand`, dealer/prevailing randomised per episode, same seed → same trajectory, rollout measured (§13), fast encoder + parity test (`tests/test_ml_fast_encode.py`: every seat, every state of full multi-hand random games and of kong-preferring random hands), behaviour-neutral engine speed-ups (§7: 2.7× engine, trajectory pin + function-level equivalence tests, no `ENGINE_VERSION` bump).

R1 progress: **done** — encoder v2 + oracle channels with a leak-guard parity test, `PolicyNet` + `OracleCritic` + auxiliary heads, auxiliary dataset/trainer (`algorithm: rl_aux`), numpy export of the served path with a parity test, `ml.aux_eval` for the exit measurements. Full run: 10,000 `FaanBot`-mix games (6.2M rows), 40k steps on CPU; best checkpoint at step 30k (val total 2.0059, flat after). Exit criteria, test split:

| Criterion | Full run | Status |
| --- | --- | --- |
| p99 ≤ 5 ms incl. encode | p50 1.46 ms, p99 3.54 ms (slow-marked test, run alone) | met |
| danger head within 0.02 AUC of `DangerNet` | legal-wait AUC on the v3 test split (1,125 games) 0.8705 vs 0.8885: −0.0181 [−0.0191, −0.0168] | met, narrowly |
| hidden-tile head beats uniform-over-unseen | NLL per unseen copy 1.1038 vs 1.1450, gain 0.0412 [0.0408, 0.0417] | met |

Other heads (1,068 test games): opponent tenpai AUC 0.862 (`DangerNet` 0.868), own win AUC 0.783, own deal-in AUC 0.580 (weakest head), shanten MAE 0.060, ukeire MAE 1.39 tiles. Artifacts (gitignored): `server/runs/rl_aux/ckpt_best.pt`, `eval_test.json`, `policy.npz`.

**Reading the results.** These heads shape the trunk; the bot's quality is decided by the R3 arena gate, not by them. Further R1 work was deferred until R3 showed a defensive weakness; it passed without one (L274.3M deals in 0.069 vs `FaanBot`'s 0.107, [rl-learnings.md §4](rl-learnings.md)), so it stays deferred.

| Head | Why it is where it is | Improvable? |
| --- | --- | --- |
| danger (−0.018 vs `DangerNet`) | `DangerNet` gets one opponent-rotated sample per opponent (3× samples, a fixed target slot); `PolicyNet` predicts all three from the seat-centred view, with one trunk shared by ~10 heads. Val loss flat from 30k to 40k steps, so more steps won't help. | yes: larger trunk (p99 3.54 ms leaves room under 5 ms), higher danger loss weight, distil `DangerNet`'s logits into the head (allowed: not `FaanBot`), more games — each about one overnight CPU run |
| hidden tiles (+0.041 nats over uniform) | much of where unseen copies sit is not inferable from public information, especially early in a hand | partly; bounded by hidden information |
| own deal-in (AUC 0.58), own win (0.78) | labels depend on future draws and on the acting policy (`FaanBot`-mix play here); once PPO changes the policy the targets move and the heads re-learn | not meaningfully before R2; not a property of the trunk |
| tenpai, shanten, ukeire | near `DangerNet` / near-exact | — |

Hard limits: danger and hidden-tile heads cannot exceed what public information determines; win/deal-in pretraining has limited lasting value because its labels are policy-dependent.

Run cost: [rl-learnings.md §7](rl-learnings.md). Reproduce: `server/runs/r1_full.sh` (generate → pack → train → eval → export); `server/runs/r1_resume.sh` resumes training from `ckpt_last.pt` and runs eval/export without regenerating.

R0 and R1 depend only on what §5 already provides.

R2 progress: **done** — `ml/train_env.py` (§7), `ml/ppo.py` (§9), `ml/curriculum.py` +
`ml/configs/rl_ppo_c0.yaml` (§10), `ml/eval_policy.py` (§12); full run on the RTX 2060 desktop
(§13). Exit criteria:

| Criterion | Result | Status |
| --- | --- | --- |
| C1 exit (§10) | update 52,402, 220.4M decisions: rolling win 0.200 (≥ 0.15), sub-min tenpai 0.108 (≤ 0.32), draws 20.2%, deal-in 0.099 over 4,000 hands | met |
| paired CI > 0 vs `EfficiencyBot` | `ckpt_C1_exit.pt` × 1 vs `EfficiencyBot` × 3, 700 fresh sets (seeds 3,000,000+), `hk_classic`: **+8.74 points/hand [+7.67, +9.80]** (bootstrap [+7.69, +9.81]); per-side detail in [rl-learnings.md §4](rl-learnings.md) | met |

The run then held C1's end parameters via `curriculum.hold_final` (§10) to 464.3M decisions
(update 110,201) and stopped for the R3 league run; final checkpoint
`runs/ppo_c1/ckpt_hold_final.pt`. Strength vs `FaanBot` plateaued at +7.8 to +9.1 points/hand from
230.9M. Curriculum timeline, metrics, evaluation over training and observed play:
[rl-learnings.md](rl-learnings.md); the CPU smoke run before it: [rl-learnings.md §7](rl-learnings.md).

Launch: `server/runs/ppo_c0_full.sh` (gitignored; resumes from
`runs/ppo_c0/ckpt_last.pt`, needs `runs/rl_aux/ckpt_best.pt`).

GPU support (§13): `device: auto | cpu | cuda` for the learner and the rollout forward,
CPU-saved checkpoints portable across devices, optional fp16 AMP, `ml.check_device`, and the WSL2
setup for the RTX 2060 desktop. CUDA tests (`-m cuda`) and throughput measured on the 2060, where
both full runs trained: learner on the GPU, rollout on the i5-10400F's cores.

R3 progress: **gate passed** (L274.3M, 2026-10-11); the league keeps running. `ml/league.py`
(pool, PFSP, personas, learned-only Elo), the league in `ml/ppo.py` (`FROZEN` seats acted by
snapshots, persona forks, PPO `init_ckpt` loading the whole learner), stage C2 in
`ml/curriculum.py` (`min_faan` 3 + 20% other presets), `ml/configs/rl_league.yaml`, and the ACH
switch (`policy_loss: ach`, §9). The full run started 2026-10-08 on the RTX 2060 from the
hold-end checkpoint (464.3M): ~1.1k learner decisions/s end to end, 0.7× the hold's ~1.6k/s
(§11). Not yet run: the ACH ablation (a second run with `policy_loss: ach`).

Run history: through 188M decisions the head-to-head against the starting policy drifted from
level to −0.83 [−1.27, −0.39] points/hand while `FaanBot` held at +9.3; the cause was `hk_casual`
dominating the batch's return variance. At 190.0M the run resumed with `reward_scale_by_ruleset`,
`pfsp_metric: points` and 400-update personas (§9, §11); eight checkpoints from 208.7M to 358.5M
are level with the starting policy at `hk_classic` (mean +0.05; one, L316.3M, crossed zero and
the next fell back). Series and per-segment metrics:
[rl-learnings.md §3–§4, §6](rl-learnings.md).

Pre-league baseline: the hold checkpoint at 462.0M (chosen in advance) already met every numeric
exit criterion on fresh seeds 5,000,000+ (+9.76 [+8.72, +10.79] vs `FaanBot` on 1,000 sets, CI > 0
against every profile; per-opponent table in [rl-learnings.md §4](rl-learnings.md)). So the league
is judged against its starting policy. The R3 gate, on fresh seeds 7,000,000+, both policies on
identical hands (points/hand, bootstrap CI; `eval_policy` seats one opponent type ×3, so mixed
tables are measured per profile; per-side detail in [rl-learnings.md §4](rl-learnings.md)):

| Criterion | Starting policy (464.3M) | L274.3M | Status (L274.3M) |
| --- | --- | --- | --- |
| paired CI > 0 vs `FaanBot`, ≥ 1,000 fresh sets | +9.99 [9.02, 10.96] | **+10.94 [9.87, 12.10]** | met |
| not worse on mixed tables (per profile, 700 sets each) | `EfficiencyBot` +11.32, `FaanBotAggressive` +10.74, `FaanBotDefensive` +9.60, `FaanBotFlushChasing` +10.03 | +14.48, +12.30, +9.88, +10.73; every CI > 0 and ≥ the starting policy's | met per profile |
| sub-min tenpai not worse | ≤ the opponents' on 2 of 5 tables | ≤ on 4 of 5 (0.048 vs `FaanBotAggressive`'s 0.032; ~20 events per cell) | met but for one table |
| stretch ≥ +5 points/game | | +10.94 points/hand (a game is ≥ 4 hands, so per hand is the stricter reading) | met |
| other presets (not a criterion) | `hk_strict` vs `FaanBot` +17.42, `hk_casual` +14.50 | `hk_strict` +25.04, `hk_casual` +18.98; head-to-head vs the starting policy at `hk_strict` **+2.47 [+1.51, +3.48]**, `hk_casual` +4.04 [−4.44, +13.39], `hk_classic` level | — |

The league's measurable gain is across presets (`hk_strict`, `EfficiencyBot` tables), not at
`hk_classic`, where the starting policy had already plateaued. L274.3M is the R4 candidate; R4
re-runs this gate on fresh seeds, and later league checkpoints are gated against L274.3M on these
seeds. Vs `OracleFaanBot` ×3 (the `ORACLE` tier then; seeds 8,000,000+, 1,000 sets): +2.88 [+1.75, +4.01]; `OracleFaanBot` ×1 vs L274.3M ×3: −1.53 [−2.22, −0.84] ([rl-learnings.md §4](rl-learnings.md)). Not yet measured: a table of mixed bot types.

R4 progress: **done** (2026-10-12) — L274.3M ships as `T4`, practice mode's "Expert":
`bots/learned.py` `LearnedBot` (`BOT_REGISTRY["LearnedBot"]`, worker tier `T4`), `"T4"` in
`POST /tables`' `bot_tiers` and the web picker, numpy in the base dependencies, weights committed
as `server/bots/weights/learned.npz` (1.7 MB; provenance, export command and why it is committed:
[bots.md §2](bots.md)). It shares `_shared_bot_pool()` with every tier: ADR 0012's head-of-line
concern is about a slow tier, and `T4` is cheaper than `T2`. Exit criteria:

| Criterion | Result | Status |
| --- | --- | --- |
| R3 gate re-run on fresh seeds | production path (`eval_policy --candidate-bot LearnedBot`, numpy forward), seeds 9,000,000+, `hk_classic`: vs `FaanBot` ×3 **+10.75 [9.64, 11.86]** on 1,000 sets (R3, `PolicyBot` on 7,000,000+: +10.94); 700 sets each vs `EfficiencyBot` +15.19, `FaanBotAggressive` +11.62, `FaanBotDefensive` +10.85, `FaanBotFlushChasing` +11.72 (R3: +14.48, +12.30, +9.88, +10.73). Every CI > 0 and contains the R3 estimate; per-side detail in [rl-learnings.md §4](rl-learnings.md) | met |
| p99 ≤ 5 ms on the server CPU | laptop (i7-1265U), `act` incl. encode, `seat_view` excluded, run alone: p50 1.8 ms, p99 2.0–3.4 ms over three runs; p99 5.3 ms in a saturated 6-worker pool. The prod box (i5-10400F) is unmeasured: `make bench-latency` there is the check | met on the laptop; prod unmeasured |
| bot load not regressed | `compute_action` in a `ProcessPoolExecutor`, 1,625 decisions: one worker, `T4` mean 1.8 ms / p99 3.8 ms vs `T2` 3.6 / 11.3 ms; six workers saturated, 1,539 vs 949 decisions/s. A worker pays once on its first `T4` job: ~35 ms (numpy import + weight load) and +21 MB RSS (49 vs 28 MB) | met: cheaper per decision than `T2` |

The numpy path is the gated torch path: on 2,479 decisions from 30 hands, `LearnedBot` picked the
same action as `PolicyBot` on the checkpoint every time (max logit difference 6.5e-5);
`tests/test_ml_learned_parity.py` pins logits and actions on the shipped file. Sub-min tenpai is
≤ the opponents' on 2 of 5 re-run tables (R3: 4 of 5); the three over are 0.033 vs 0.032, 0.042
vs 0.036 and 0.046 vs 0.033, at ~20 events per cell.

Since [ADR 0022](decisions/0022-oracle-learned-tier.md) the `ORACLE` tier ("Impossible") is this
policy plus exact-information vetoes and loads the same `learned.npz`, so new weights change both
tiers. Shipping them is [bots.md §2](bots.md)'s runbook: export, provenance, parity, this R4 gate
(Expert), the ADR 0022 gate (Impossible), `make bench-latency`.

## 15. Risks

| Risk | Handling | Status |
| --- | --- | --- |
| env slower than the learner end-to-end | R0 measurement; mypyc → Rust ladder (§7) | not hit: on the 2060 neither leg dominates (learner ~55% of wall time, §13); engine compilation not needed |
| curriculum stalls | oracle draws, annealed shaping, auxiliary pretraining; §10 contingency | not hit: C1 exited at 220.4M, the contingency never enabled ([rl-learnings.md §2](rl-learnings.md)) |
| heavy-tailed payouts destabilise the value | PopArt, oracle critic, larger batches; per-ruleset reward scale so an alt preset's tail (`hk_casual`) can't dominate a batch (§9, §11) | hit in C2: `hk_casual` supplied ~65% of the return variance and the league regressed to −0.83 vs its start by 188.2M; fixed by `reward_scale_by_ruleset` at 190.0M ([rl-learnings.md §6](rl-learnings.md)) |
| passive/collusive self-play equilibrium | draw-rate canary (`league_draw_self` vs `_past` / `_persona`, §11), league diversity, held-out heuristic eval | watched: self-play draws rose 20% → 31–40% in the C1 hold while strength vs `FaanBot` rose, and sit at 0.32–0.36 in the league with eval-table draws 25–28% ([rl-learnings.md §3, §6](rl-learnings.md)): read the canary with held-out eval, not alone |
| league rollout cost | `FROZEN` rows are env steps and forwards without samples: 0.59× rollout at 1 learner seat per snapshot table on CPU (§11); `seat_learners: 2` or a lower snapshot share if end-to-end throughput drops too far | hit as predicted: 0.7× end to end on the 2060 (~1.1k vs ~1.6k/s), accepted |
| PFSP chasing stale stats | the learner moves while counts age: decay 0.999 per update, ½ prior; an unvisited snapshot drifts back to the prior and gets sampled again | open |
| PFSP/Elo measuring style, not strength | the win share x moves when the policy trades win frequency for win size; `pfsp_metric: points` (§11) ranks by the points difference instead, and x stays in `league_vs` as the style read-out | hit in C2 (x ≈ 0.48 against equal-strength snapshots, PFSP uniform, Elo falling); `pfsp_metric: points` since 190.0M |
| shaping residue (speed bias) | β = 0 well before any gate; sub-min tenpai canary | not seen: sub-min tenpai 0.018–0.067 vs `FaanBot`'s 0.020–0.040 on the same seeds since 326.0M ([rl-learnings.md §4](rl-learnings.md)) |
| hidden info leaking into the policy | encoder parity test; `visible_meld_counts34` rule (§5); oracle channels at keep prob 0 before any gate | guarded: tests in place, eval-path permutation check clean (§12) |
| `ENGINE_VERSION` bump mid-run | pinned in run metadata; a ruleset-encoding-only change (1.0.0 → 1.3.0) is carried by `ml.migrate_ckpt` (§9) into a new run dir | hit once: 1.0.0 → 1.3.0 at 98.6M in R2, migrated ([ADR 0020](decisions/0020-hk-scoring-table-alignment.md)) |
