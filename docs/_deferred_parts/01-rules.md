## Multi-win (一炮多響)

Provenance: `01-rules-spec.md` §6 (claim priority), §10 (`RuleSet.multi_win`), §11 (edge case
7) — deferred per canonical decision D7: v1 is single-winner; 一炮多響 is deferred past v1.

**Full behavior (post-v1):** when two or more players can declare a win off the same
discard, instead of resolving to a single winner by seat-order tiebreak
(`(claimer_seat - discarder_seat) % 4`, smallest wins — the v1 rule, see
`01-rules-spec.md` §6), all claimants win simultaneously. The discarder pays each winner in
full (i.e. the discarder's total liability is the sum of `P` for every winning hand, not
split). Each winning hand is scored independently — no `1.5×` self-draw-style adjustment,
since this is still a discard win for each claimant. Dealer continuity (連莊) follows
whichever house rule the table has configured for multi-winner hands (commonly: dealer
repeats only if the dealer is among the winners).

Needs before un-deferring:
- Decide whether all winners are required to reveal their full hand simultaneously or in
  seat order (affects information leakage in the reveal sequence).
- Decide interaction with `pao_rules` (包) if a discarder is liable under a responsibility
  rule for one hand but not another among the multiple winners.
- Client/protocol support for a multi-winner `SCORING` payload (currently single-winner
  shaped, see `02-protocol.md`).

`RuleSet.multi_win: bool` field stays in the dataclass as a reserved flag (`False` in v1) so
the shape doesn't need to change when this is implemented.
