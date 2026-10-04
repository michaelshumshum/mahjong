# 0017. TypeScript 7 as the primary compiler

- **Status:** Deferred (upstream blocker)
- **Date:** 2026-09

## Context

`typescript` is pinned to `^6.0.3` as the primary dependency. TS7 is installed only as an aliased
secondary package (`@typescript/native`, `npm:typescript@^7.0.2`) and used exclusively via
`svelte-check --tsgo` (`web/package.json`'s `check`/`check:watch`).

`svelte-check`'s CLI does an unconditional top-level `require('typescript')` that must resolve to
TS5/6 even in `--tsgo` mode (`sveltejs/language-tools#3063`). TS7 has no stable programmatic API
for embedding tools yet — Volar, svelte-check, Vue and Astro all hit the same wall. Microsoft's TS7
announcement: "tools which embed TypeScript into their own compilers and language services can only
currently rely on TypeScript 6.0 ... We expect this to be a point-in-time issue." The svelte-check
maintainer (2026-08-31): even TS 7.1's "content mapper" support "will currently still require both
TypeScript 6 and 7."

## Needs before reviving

- TypeScript ships a stable embeddable API, and `svelte-check` drops the TS6-primary requirement.
- Meanwhile, if relying on `--tsgo`: re-check `sveltejs/language-tools#3120` (includes more files
  than expected) and `#3095` (crashes on Linux/arm64; CI is x86_64).
- Known `--tsgo` quirk in this project: `$state<T>(...)`/`$derived<T>(...)` explicit generics error
  under `--tsgo` but not `tsc`; use `let x: T = $state(...)` instead.

## When it lands

Drop the `@typescript/native` alias, bump `typescript` to current TS7, remove `--tsgo` from
`check`/`check:watch`, and delete the rationale note in `web/AGENTS.md`.
