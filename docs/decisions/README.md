# Decision records

Why things are the way they are, what was tried and removed, and designs parked for later. The
reference docs in `docs/` describe the system as it is; these records hold the history behind it.

| Status | Meaning |
| --- | --- |
| Accepted | in effect; the reference docs describe the result |
| Deferred | designed or scoped, not built — read the record before reviving |
| Rejected | tried or considered and dropped |
| Historical | a retired plan, kept for the record |

Before reviving a deferred record, re-read the reference docs it links: the design around it has
moved on.

| # | Title | Status |
| --- | --- | --- |
| [0001](0001-guest-only-identity.md) | Guest-only identity | Accepted |
| [0002](0002-dom-rendering.md) | DOM/CSS rendering, no PixiJS | Accepted |
| [0003](0003-product-scope.md) | Product scope | Accepted |
| [0004](0004-claim-forfeit-on-disconnect.md) | A mid-claim-window disconnect forfeits the offer | Accepted |
| [0005](0005-client-entropy-fairness.md) | Client-contributed entropy for provable fairness | Deferred |
| [0006](0006-multi-node-and-durability.md) | Multi-node scaling and mid-game durability | Deferred |
| [0007](0007-multi-win-and-pao.md) | Multi-win (一炮多響) and responsibility payments (包) | Deferred |
| [0008](0008-chess-clock-bonus-bank.md) | Chess-clock bonus bank | Deferred |
| [0009](0009-liveness-heartbeat.md) | Liveness heartbeat | Deferred |
| [0010](0010-client-scope-cuts.md) | Client features cut from scope | Deferred |
| [0011](0011-replay-viewer.md) | Replay viewer needs a server re-redaction endpoint | Deferred |
| [0012](0012-searchbot-removed.md) | T3 `SearchBot` built and removed | Rejected |
| [0013](0013-oracle-full-information.md) | `ORACLE` as a full-information `FaanBot` | Accepted |
| [0014](0014-ruleset-aware-bots.md) | Ruleset-aware bots | Accepted |
| [0015](0015-bot-personas.md) | Bot personas | Deferred |
| [0016](0016-human-records-as-training-data.md) | Human game records as training data | Deferred |
| [0017](0017-typescript-7-svelte-check.md) | TypeScript 7 as the primary compiler | Deferred |
| [0018](0018-milestone-plan.md) | Milestone plan and timeline | Historical |
| [0019](0019-oracle-improvements-plan.md) | `ORACLE` improvements plan | Accepted |
| [0020](0020-hk-scoring-table-alignment.md) | Scoring table aligned with standard HK mahjong | Accepted |

New records: next free number, `NNNN-kebab-title.md`, with Status, Date, Context, Decision (or
Design sketch), Consequences (or Needs before reviving).
