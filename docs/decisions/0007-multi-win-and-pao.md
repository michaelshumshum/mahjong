# 0007. Multi-win (一炮多響) and responsibility payments (包)

- **Status:** Deferred
- **Date:** 2026-09-14

## Context

Two scoring variants were scoped out to keep the claim resolver and payout single-winner. Both
`RuleSet` fields exist as reserved flags so the shape won't change: `multi_win` and `pao_rules`,
both `False` and unread ([rules.md §10](../rules.md)).

## Multi-win

Today a Win-vs-Win tie resolves to the claimant nearest the discarder in turn order
([rules.md §6](../rules.md)). With multi-win, all claimants win simultaneously: the discarder pays
each winner `P` in full (no split), each hand is scored independently (no self-draw adjustment),
and dealer continuity follows a house rule (commonly: dealer repeats only if among the winners).

Needs before reviving:

- Simultaneous vs. seat-order reveal of the winning hands (affects information leakage).
- Interaction with 包 when the discarder is liable for one winner's hand but not another's.
- A multi-winner `hand_end`/scoring payload; today's is single-winner shaped.

## Responsibility payments (包)

Reference rules are listed in [rules.md §8](../rules.md) (九張包, 十二張包自摸, 五子包生, 大三元/大四喜包).

Needs before reviving: per-rule trigger detection in the engine (which discard "fed" which meld),
and payout routing that overrides `discard_payment`.
