# Server constant/type ownership (refactor 2026-10-15, round 2 2026-10-16)

Import shared values from their owners. Don't re-declare them locally.
- Tile geometry: `mahjong_core/tiles.py` holds N_TILE_TYPES, COPIES_PER_TYPE, N_SUITED_TYPES, RANKS_PER_SUIT, N_FLOWERS, WIND/DRAGON/ORPHAN_TYPES and ORPHAN_INDICES.
- Action-id layout: `mahjong_core/ml.py` holds N_ACTIONS, DISCARD_BASE, CONCEALED_KONG_BASE, ADDED_KONG_BASE, PASS_ID..WIN_ID and CHOW_IDS.
- Seats: `mahjong_core/seats.py` N_SEATS + validate_seat (import-free; state.py can't own them since it imports wall/melds, which need N_SEATS). 4s that are tile copies (`tile_type * 4 + offset`, `4 - seen`), the deal's 4-tile blocks and ML feature-width sums stay literal.
- Hand sizes: `mahjong_core/wall.py` DEALT_HAND_SIZE, HAND_SIZE (= +1; hand_check and api_models import it).
- `MAX_FAAN_CAP` (config.py, max of _VALID_FAAN_CAP) sizes payout's points tables. `LIMIT_FAAN` (patterns.py) is the scoring limit and only coincides.
- Claim drivers: `mahjong_core/claims.py` pending_claim_seats(state) — offers order, callers rng.choice/min over it. Trajectory-pin tests keep their inline copy on purpose.
- Engine events: `mahjong_core/events.py`.
- Offline harness: `bots/base.py` holds NO_DEADLINE and GAME_STEP_CAP=8000. ml/env.py's 2000 is a separate per-hand cap.
- Bot tiers: `bots/tiers.py` BotTier StrEnum (wire values), BOT_TIERS, DEFAULT_BOT_TIER, LEARNED_TIERS.
- Bot view features: `bots/features.py` add_meld, claimed_tile_type (efficiency+faanbot), own_hand34, seen34.
- ML: `ml/encode.py` PAD, MAX_DISCARDS, PADDED_*, PHASE_INDEX, N_OPPONENTS; `ml/raw.py` relative_seats; `ml/encode_v2.py` layout_slices (policy_net imports it); `ml/stop_signal.py` StopSignal (SIGINT/SIGTERM flag for train/aux_train/ppo/generate_*); `ml/splits.py` SPLITS.
- app: `app/errors.py` exceptions, wire `ErrorCode` StrEnum, TABLE_CLOSED_ERROR. `app/table_types.py` dataclasses + `type SeatStatus`/`type WireSeatStatus` aliases. `app/views.py` CLAIM_KIND_WIRE, `type ClaimChoice`, `type WindName`. `app/protocol.py` `type Seat`.
- Wire typing: protocol.py fields reuse core enums (Phase, MeldKind, ClaimKind, ActionKind, HandOutcome, WinType) — gen_protocol emits StrEnums AND `type X = ...` aliases as named TS types (protocol.md §6). views.py can't import protocol.py (cycle via bots -> views), so wire aliases views needs live in views.
- Client->server seat fields deliberately stay `int`; AckPayload.error stays `str`.

Tests: shared helpers are plain modules `tests/game_state.py`, `hands.py`, `decisions.py`, `ws_frames.py`, `game_records.py`; `session` fixture in conftest (testing.md §3).

Deliberately not extracted:
- migrate_ckpt RULESET='hk_classic' pinned; flower instant-win constants in engine; env reads stay at their read site; views *Wire dataclasses beside Entitlement.
- EfficiencyBot/FaanBot identical `act` dispatch (would need a base class); encode v1/v2 `_thermo`; numerically different `_sigmoid`s; `n_parameters` (danger_model/policy_net).
