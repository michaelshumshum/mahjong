# Server constant/type ownership (refactor 2026-10-15)

Import shared values from their owners. Don't re-declare them locally.
- Tile geometry: `mahjong_core/tiles.py` holds N_TILE_TYPES, COPIES_PER_TYPE, N_SUITED_TYPES, RANKS_PER_SUIT, N_FLOWERS, WIND/DRAGON/ORPHAN_TYPES and ORPHAN_INDICES.
- Action-id layout: `mahjong_core/ml.py` holds DISCARD_BASE, CONCEALED_KONG_BASE, ADDED_KONG_BASE, PASS_ID..WIN_ID and CHOW_IDS.
- Engine events: `mahjong_core/events.py`. engine.py still imports them, so `from mahjong_core.engine import Drawn` works at runtime, but no longer appears in `__all__`.
- Offline harness: `bots/base.py` holds NO_DEADLINE and GAME_STEP_CAP=8000. ml/env.py's 2000 is a separate per-hand cap.
- Bot tiers: `bots/tiers.py` holds the BotTier StrEnum (values are wire strings), BOT_TIERS, DEFAULT_BOT_TIER and LEARNED_TIERS. bots/worker.py no longer exports them.
- ML format: `ml/encode.py` holds PAD, MAX_DISCARDS, PADDED_WIDTH/PADDED_POSITIONS (torch-free, so used by export.py), PHASE_INDEX and N_OPPONENTS. `ml/splits.py` holds SPLITS.
- app: exceptions and TABLE_CLOSED_ERROR are in `app/errors.py`. SeatBinding, Command, Envelope, BotJobTag, BotResult, SeatDisconnected, TableSettings and SeatStatus/WireSeatStatus are in `app/table_types.py`. REST models are in `app/api_models.py`. `CLAIM_KIND_WIRE` is in `app/views.py`, and ws.py derives the inverse from it.

Deliberately not extracted:
- migrate_ckpt RULESET='hk_classic' is pinned to a historical checkpoint.
- payout._MAX_FAAN=13 is tied to the hand-authored payout tables.
- Flower instant-win constants stay in engine because only engine uses them and they are not a scoring Pattern.
- Env reads (think delay, grace) stay where their read timing is defined.
- views *Wire dataclasses stay beside their Entitlement annotations.
