"""Named `RuleSet` presets (docs/05-roadmap.md "Ruleset presets") -- the curated starting
points a table-creation UI offers next to "custom" (an arbitrary `RuleSet.from_dict` payload,
no preset id attached). Presets are plain data, not a new engine concept: each is just a
`RuleSet` instance `mahjong_core` already knows how to construct and validate.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .config import DEFAULT_RULESET, DiscardPayment, HandSet, RuleSet, ScoreTable

RULESET_PRESETS: dict[str, RuleSet] = {
    "hk_classic": DEFAULT_RULESET,
    "hk_casual": RuleSet(min_faan=1, faan_cap=13, score_table=ScoreTable.FULL_SPICY),
    "hk_strict": RuleSet(
        min_faan=5,
        hand_sets=frozenset({HandSet.CLASSIC, HandSet.NEW_6}),  # NEW_18 off
        discard_payment=DiscardPayment.HALF,
    ),
}

DEFAULT_PRESET_ID = "hk_classic"


def preset_id_for(ruleset: RuleSet) -> str | None:
    """The `RULESET_PRESETS` key `ruleset` matches field-for-field, or `None` if it doesn't
    match any of them -- a custom ruleset, whether or not it happens to equal a preset (that
    case is indistinguishable from, and behaves identically to, actually picking the preset)."""
    for preset_id, preset in RULESET_PRESETS.items():
        if ruleset == preset:
            return preset_id
    return None


def resolve_ruleset(ruleset: str, rules: Mapping[str, Any] | None) -> RuleSet:
    """A table-creation ruleset choice -> the `RuleSet` to construct the table with. `ruleset`
    is a `RULESET_PRESETS` key, or `"custom"` to build from `rules` (a `RuleSet.from_dict`-shaped
    mapping) instead. Shared by every table-creation entry point (`app/main.py`'s `POST /tables`
    body, `app/ws.py`'s `?ruleset=`/`?rules=` WS-connect fallback) so "what a ruleset choice
    means" has exactly one implementation regardless of transport. Never raises: an unknown
    preset id, a missing `rules` mapping, or one that fails `RuleSet`'s own validation
    (`__post_init__`, e.g. `min_faan` outside its enum) all silently fall back to the default
    preset rather than rejecting the request -- matches this codebase's existing posture toward
    client input elsewhere (`?practice=`'s bool coercion, `_normalize_name`'s default-instead-
    of-error)."""
    if ruleset == "custom" and rules is not None:
        try:
            return RuleSet.from_dict(rules)
        except (KeyError, TypeError, ValueError):
            pass
    return RULESET_PRESETS.get(ruleset, DEFAULT_RULESET)
