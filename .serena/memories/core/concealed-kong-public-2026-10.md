# Concealed kongs are public (ADR 0023, 2026-10-14)

- HK rule (zh.wikipedia 香港麻雀): 暗槓 must be shown, unlike Taiwan. Display: end tiles face-down, middle two face-up.
- Wire: every `meld` carries real `tiles`; `MeldPayload.count`, `ConcealedKongWire`, per-viewer `_meld_wire`/`hand_history_wire` redaction removed.
- Client: `web/src/lib/table/meld-face.ts` `meldTileFace` is the single place that decides backs; every meld renderer (OpponentRegion, YourSeatRegion, FaanBreakdown, WinningHand, AnimationDemoPanel) uses it. `MeldState.tiles` is never null now.
- Bots/ML: `seen34`, `raw.visible_meld_counts34`, `fast_encode`, `encode_v2.policy_raw` count opponents' concealed kongs; aux hidden-tile target no longer treats them as unseen. The concealed-kong count scalar stays.
- Shipped `learned.npz` re-gated zero-shot (no retrain), all gates pass; data/rollouts before 2026-10-14 used the old hidden encoding.
- Scoring here: a concealed kong breaks 門前清 but counts for 四暗刻 (rules.md §7 notes ³/⁵).
- Gotcha: `web/test-results/` is root-owned (docker); run Playwright natively with `--output <scratch dir>`. Full e2e under CPU load flakes on 30s timeouts.
