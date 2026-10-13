# Create-table dialog / custom rules editor + provable fairness (2026-10-13/14)

Uncommitted at session end (user hadn't asked to commit).

- Two views in CreateTableDialog: presets list -> Custom opens RulesEditor.svelte (tabs Scoring/Hands/Play/Table via shared TabBar.svelte, which Settings now also uses). Custom radio swaps the view, so e2e must `.click()` it, not `.check()`.
- RULESET_PRESET_RULES (lib/net/ruleset.ts) mirrors server presets.py field-for-field; GUIDE_PRESET_RULES in faan-guide.ts derives from it. Update together with server.
- INERT_RULE_FIELDS: 7 RuleSet fields with no server reader (self_draw_multiplier, thirteen_orphans_wait_bonus, four_kong_abort, nine_terminals_abort, tenpai_payments, multi_win, pao_rules). Hidden, always posted at defaults. Implement one server-side -> drop it from the list and add a control.
- provable_fairness now implemented: app/fairness.py (16-byte nonce per hand, minted lazily in Table._seed_commit so hand_start and state_sync agree), hand_start/state_sync.seed_commit, hand_end/hand_history.fairness (keys omitted when off). game_seed now secrets.randbits(63) (was time_ns -> grindable once hand_seed is revealed; 63 bits because seed columns are signed BIGINT). tools/verify_fairness.py checks commit + prints wall. Client: FairnessBadge in HandEndOverlay, WebCrypto check (lib/net/fairness.ts); history-backfilled hands have commit=null -> "unverifiable".
- 雞糊 moved to its own guide tab 0 (scores 0, CHICKEN_HAND_FAAN).
- hk_strict verified = hk_classic + min_faan 5 + discard_payment HALF. FaanBot selfplay 5 games: strict 95% draws, 582 hands (dealer_repeat_on_draw keeps dealer -> games balloon); classic 37% draws/46 hands; casual 0%/28 hands. Payments/min_faan invariants held. Preset values NOT changed (RL/bot pins depend on them) -- recommendation pending with user.
- resolve_ruleset silently falls back to hk_classic on invalid custom body -> client validation (invalidRuleFields) is the only guard.
- Last setup stored at mahjong:createTableSetup:v1. Specs that vi.mock settings-storage must add loadCreateTableSetup/saveCreateTableSetup.
- Screenshot script: segmented highlight has a ~150ms transition; wait before capture.
- Native playwright: test-results/ is root-owned from docker runs -> pass `--output <scratch>`.
