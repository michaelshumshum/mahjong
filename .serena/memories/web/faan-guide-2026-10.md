# Faan guide overhaul (2026-10-22)

Full description: docs/frontend.md "Faan guide and language toggle"; POST /score in docs/protocol.md §10.

- Guide faan values now come from generated `FAAN_PATTERNS`/`CHICKEN_HAND`/`POINTS_TABLES` in `web/src/lib/net/protocol.constants.ts` (make proto, gen_protocol.render_constants). Before this, the hand-placed GUIDE had 5 wrong values (清一色 6→7, 小三元 3→5, 小四喜 5→6, 大三元 7→8, 大四喜 8→limit). RulesEditor's "add override" also used the tier number as the default value; it now uses `OVERRIDABLE_PATTERNS[].faan`.
- `GUIDE_ENTRIES` = presentation only (desc, example with `*` key-group prefix, tags, related). `scoredEntries(rules|null)` derives tabs.
- Hand checker: `mahjong_core/hand_check.py` `check_hand` (concealed 14 tiles, last = winning tile) behind `POST /score`; no rate limit.
- MOCK_SCENARIOS hand results now use Chinese pattern keys (like live hand_end) so FaanPatternName links render under ?mock=. Demo components (FaanBreakdownDemo, ScoreSheetDemo) still use English literals → not linkable there.
- Screenshot gotcha: chip border transitions + hover make a just-clicked chip look unpressed; `page.mouse.move(0,0)` + 300ms wait before capture.
- Open: docs/rules.md §7 says 小四喜 replaces 門風/圈風 but `_SUPERSEDES` in scoring/patterns.py has no 小四喜 entry — doc/code mismatch, not resolved.
- `make lint` fails on pre-existing ruff errors in server/runs/** (analysis scripts), unrelated.
