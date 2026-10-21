"""Named `RuleSet` presets — curated starting points a table-creation UI offers next to
"custom". Plain data, not a new engine concept: each is just a `RuleSet` instance.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .config import DEFAULT_RULESET, DiscardPayment, HandSet, RuleSet, ScoreTable
from .scoring.faan import validate_faan_overrides

RULESET_PRESETS: dict[str, RuleSet] = {
    "hk_classic": DEFAULT_RULESET,
    "hk_casual": RuleSet(
        min_faan=1,
        faan_cap=13,
        score_table=ScoreTable.FULL_SPICY,
        hand_sets=frozenset({HandSet.CLASSIC, HandSet.NEW_6, HandSet.NEW_18}),
    ),
    "hk_strict": RuleSet(
        min_faan=5,
        discard_payment=DiscardPayment.HALF,
    ),
}

DEFAULT_PRESET_ID = "hk_classic"


def preset_id_for(ruleset: RuleSet) -> str | None:
    """The `RULESET_PRESETS` key `ruleset` matches field-for-field, or `None` for a custom
    ruleset (including one that happens to equal a preset by coincidence)."""
    for preset_id, preset in RULESET_PRESETS.items():
        if ruleset == preset:
            return preset_id
    return None


def resolve_ruleset(ruleset: str, rules: Mapping[str, Any] | None) -> RuleSet:
    """A table-creation ruleset choice -> the `RuleSet` to construct the table with. `ruleset`
    is a `RULESET_PRESETS` key, or `"custom"` to build from `rules`. Never raises: an unknown
    preset id or a `rules` mapping that fails validation (`validate_faan_overrides` included)
    silently falls back to the default preset rather than rejecting the request. A custom body
    must also pass `RuleSet.check_client_bounds` (docs/rules.md §10)."""
    if ruleset == "custom" and rules is not None:
        try:
            custom = RuleSet.from_dict(rules)
            validate_faan_overrides(custom.faan_overrides)
            custom.check_client_bounds()
            return custom
        except (KeyError, TypeError, ValueError):
            pass
    return RULESET_PRESETS.get(ruleset, DEFAULT_RULESET)
