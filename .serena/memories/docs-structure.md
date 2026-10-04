# docs structure (reorganized 2026-10-04)

- `docs/*.md` are reference docs (describe what IS): architecture, rules, protocol, frontend, bots, ml, infra, testing. Index: `docs/README.md`.
- `docs/ml.md` is the one exception: stays plan/roadmap-shaped (§14 milestones, §15 risks) while the RL agent is in progress.
- `docs/decisions/NNNN-title.md` = ADR log (Accepted / Deferred / Rejected / Historical). History, measurement logs (arena runs), removed designs (T3 SearchBot = 0012, rollout OracleBot = 0013), deferred features (multi-win 0007, heartbeat 0009, replay viewer 0011, ...) and the retired milestone plan (0018, cite as `docs/decisions/0018-milestone-plan.md M3`) live there. Index: `docs/decisions/README.md`.
- Old files gone: `05-roadmap.md` (split into infra/testing/ADRs), `99-deferred.md` (→ ADRs). Old `NN-name.md` filenames renamed (no number prefix).
- Code cites `docs/<doc>.md §N` everywhere (~440 citations). Renumbering a section = `git grep 'docs/<doc>.md'` and update. Named subsections cited by title (e.g. frontend.md §7 "`/table/[id]` wiring", "Pre-game states", "Practice mode", "Game-end summary").
- Section map highlights: frontend §7 = Routes, §8 = assets+SCSS, §9 = a11y/i18n; bots §6 = difficulty, §7 = arena, §8 = ruleset awareness, §9 = ORACLE, §10 = known issues; infra §2 = toolchain/native dev (mise), §3 = process model, §9 = CI; testing §1 = strategy, §2 = Vitest gotchas.
- Routing hook `.claude/hooks/enforce-routing-table.sh` uses the new paths; `mise.toml` routes to docs/infra.md.
- Gotcha: `make test-web` currently fails with ERR_PNPM_OUTDATED_LOCKFILE inside the container (stale web image/`web-modules` volume, not the repo); `cd web && CI=true pnpm test` natively passes. Rebuild the web image / `docker volume rm mahjong_web-modules` to fix.
- Native dev needs `CORS_ORIGINS=http://localhost:5173` on the API or the web dev server can't reach it.
