"""Per-hand commit/reveal for `RuleSet.provable_fairness` (docs/protocol.md §3 "Fairness").

The nonce is server-side randomness, so it lives in `app/`, never in the pure engine; the
`hand_seed` it commits to is the engine's own `derive_hand_seed(game_seed, hand_no)`.
"""

from __future__ import annotations

import hashlib
import secrets

NONCE_BYTES = 16
# signed BIGINT columns (games.seed, hand_records.seed) cap the seed at 63 bits
GAME_SEED_BITS = 63


def new_game_seed() -> int:
    """Unpredictable game seed. A revealed `hand_seed` is `SHA256(game_seed || hand_no)`, so a
    guessable seed (a clock reading) would let a player grind it and predict every later wall."""
    return secrets.randbits(GAME_SEED_BITS)


def new_nonce() -> bytes:
    return secrets.token_bytes(NONCE_BYTES)


def seed_commit(hand_seed: bytes, nonce: bytes) -> str:
    return hashlib.sha256(hand_seed + nonce).hexdigest()


def fairness_reveal(hand_seed: bytes, nonce: bytes) -> dict[str, str]:
    return {"hand_seed": hand_seed.hex(), "nonce": nonce.hex()}
