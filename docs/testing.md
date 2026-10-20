# Testing

Policy — commands, `mahjong_core` purity, golden fixtures, seeded determinism — is in root
`AGENTS.md`'s Testing section. This doc covers strategy per layer and the implementation-level
gotchas that don't belong inline in `web/AGENTS.md` or `server/AGENTS.md`.

## 1. Strategy

| Layer | Approach |
| --- | --- |
| `mahjong_core` | Table-driven unit tests + `hypothesis` property tests, no mocks. **Invariants:** tile conservation (all 144 accounted for in hands + melds + pool + wall + flowers at every step); hand sizes consistent with meld count; `legal_actions` never empty in an active phase; every game terminates. |
| Scoring | Hand-authored parametrized cases in `tests/test_scoring.py`/`test_faan.py`/`test_payout.py` (145 tests): every registered pattern exercised positively, every [rules.md §11](rules.md) edge case named. Shanten cross-checked against `MahjongRepository/mahjong` ([bots.md §3](bots.md)). |
| Claim windows | Deterministic tests with injected arrival order — a slow high-priority win beats a fast chow, stale `window_id`s drop, early exit fires when it should. |
| Redaction | Schema walker over every message type × every recipient ([architecture.md §5](architecture.md)); fails loudly on a new unannotated field. |
| Server | `httpx` + WS test client. `tests/test_full_game_e2e.py` drives four real WS clients through a full `EAST_ONLY` game — a claim exchange, a self-draw win, a mid-claim-window disconnect/reconnect — checking every frame against `Entitlement` rules live. |
| Protocol | `proto-check` CI job: regenerated TS must match committed TS ([infra.md §9](infra.md)). |
| Client | Vitest on the pure reducer and components (§2); Playwright e2e for full flows, including a live game against bots (`web/src/routes/table/[id]/live.e2e.ts`). |
| Bots | Arena paired-difference merge gate ([bots.md §7](bots.md)). |
| Load | Not built. Target: replay bot sessions as real WS clients, 200 concurrent tables on one node. |

**Fast vs. slow.** `@pytest.mark.slow` marks soaks, the real-bot `ProcessPoolExecutor`
practice-mode e2e, and hypothesis runs. Local `make test*` runs the fast suite only; `make
test-server-slow` runs the slow suite (`N=` overrides the soak's game count); CI runs both on every
push, the soak capped at `--games=1000` ([infra.md §9](infra.md)). The slow suite is real coverage:
it caught a tile-conservation bug in `mahjong_core.engine`'s claimed-win path that only thousands of
randomized games reach.

**Self-play soak.** `make selfplay` / `pytest -m slow -k selfplay` plays N complete games with four
`RandomBot`s — no illegal states, no deadlocks, every game terminates. It runs with
`dealer_repeat_on_win`/`dealer_repeat_on_draw` off, not `DEFAULT_RULESET`: `RandomBot` wins so
rarely that repeat-on-draw can chain 150+ hands before a round rotates, turning a legitimate
slow-converging config into flakiness. With repeats off, a game is exactly 4/8/16 hands for
`EAST_ONLY`/`EAST_SOUTH`/`FULL`. The repeat paths have dedicated unit coverage in `test_engine.py`.

**Latency tests** (`@pytest.mark.slow` + `@pytest.mark.latency`, checked by `tests/latency.py`'s
`check_latency`). Each times its decision back to back with a reference on the same input, so both
see the same CPU load:

| Test | Measured | Reference | Gate (CI) |
| --- | --- | --- | --- |
| `test_learned_bot.py::test_single_decision_latency` | `T4` via `compute_action` | `T2` | p99 < reference p99 |
| `test_oracle_learned.py::test_served_tier_decision_latency` | `ORACLE` via `compute_action` | `T4` | p99 < 2 × reference p99 |
| `test_ml_policy_export.py::test_single_sample_latency_with_encoding` | numpy policy serve, full size | `FaanBot` decision | p99 < reference p99 |
| `test_ml_export.py::test_three_opponents_score_faster_than_a_faanbot_decision` | `DangerNet` ×3 opponents | `FaanBot` decision | median < 3 × reference median |

The `DangerNet` gate was 1× until `standard_shanten`'s pairwise merge ([bots.md §3](bots.md))
made a `FaanBot` decision ~4× cheaper (~1 ms); `DangerNet` is offline-only (never served), so
its reference was rebased rather than its forward pass held to the new `FaanBot`. The `T4` and
policy-serve gates still hold at 1× on p99, but their medians now sit level with `T2`'s.

Where each budget is enforced:

| Check | Where | Gating |
| --- | --- | --- |
| ratio above | every slow-suite run, CI included (`-n auto`) | yes |
| absolute p50/p99 | printed; appended to `$GITHUB_STEP_SUMMARY` in CI | no: contended runner numbers, a trend only |
| [ml.md §6](ml.md)'s 5 ms p99 | `make bench-latency` (`LATENCY_BUDGET_MS=5`, serial, `-m latency`) on the CPU that matters: the laptop or prod host. Part of the weights re-gate runbook ([bots.md §2](bots.md)) | yes, when run |

Why this split: an absolute 5 ms on a shared runner under `-n auto` measured the runner, not the
code (53 ms p99 on `main`); a slower dev box misses it even serially (`T4` p99 6–8 ms on a 2.1 GHz
Xeon). Rejected:

| Option | Why not |
| --- | --- |
| CPU-normalised budget (calibrate on a reference workload) | the scaling factor depends on the workload mix (numpy vs pure Python) and adds its own noise; the paired ratio already is a same-runner calibration, against the code it competes with |
| separate non-gating benchmark job | another `uv sync` on the same shared runner for numbers the summary already records |
| dedicated runner | standing infra for one check; nothing else needs it |
| `pytest-benchmark` | a new dependency that still times absolute numbers on the shared runner |
| absolute check only in `make test-server-slow` | that target runs `-n auto`, the same contention as CI |

`tests/conftest.py` pins `OPENBLAS_NUM_THREADS=1`, as a bot pool worker runs; without it every
xdist worker's numpy spawned a thread per core and the tests timed the oversubscription.

**Determinism.** A failing game reproduces from `(ruleset, seed, actions)`.

## 2. Web (Vitest)

### 2.1 `client` vs `server` project — runes need a real browser

A `*.svelte.ts` file's runes (`$state`/`$effect`) must run under `vite.config.ts`'s vitest `client`
project, not `server`. Vitest's `node` environment loads modules through Vite's SSR target even
with `environment: 'jsdom'`, and Svelte's server runtime never runs `$effect` — it silently no-ops,
which reads like "nothing subscribed yet," not "this never ran."

The `client` project uses real browser mode (`@vitest/browser-playwright`, reusing the e2e
Playwright install). Name the spec `*.svelte.spec.ts` to route it there — a plain `.spec.ts`
importing a `.svelte.ts` module still runs under `server`, and its `$effect`s never fire.

### 2.2 Mounting a `.svelte` component — `test-render.ts` vs inline mount

`lib/table/test-render.ts` (`render`/`cleanup`/`cleanupAll`, wrapping Svelte's `mount`/`unmount`)
is the shared helper for table-surface specs; `afterEach(cleanupAll)` covers specs that don't keep
each `render()` result.

A route's top-level `+page.svelte` needs SvelteKit context the table components don't
(`$app/navigation`, `$lib/net/lobby`'s `$env/dynamic/public` — §2.4), so
`routes-tests/*.svelte.spec.ts` mount inline with plain `mount`/`unmount`. `test/mocks.ts`
(`createMessagesProxy`) covers what those routes need mocked.

### 2.3 `vi.mock`/`vi.hoisted` under the `client` project's real browser mode

Vite's import analysis rewrites every static `import` into an awaited dynamic `import()`, so code
running *synchronously* before imports resolve — a `vi.hoisted()` body in particular — can't
reference an imported binding. Doing so throws `[vitest] There was an error when mocking a module`
at hoist time, which reads like a broken mock rather than a timing issue.

- `vi.mock(...)`'s factory may reference an import: factories run lazily, after imports resolve
  (e.g. `routes-tests/tables/TableCard.svelte.spec.ts`'s
  `vi.mock('$lib/paraglide/messages.js', () => ({ m: createMessagesProxy() }))`).
- When a factory needs module-scope data (a fixture, a prior `vi.fn()`), use a **dynamic `import()`
  inside the factory** (`routes-tests/lobby/page.svelte.spec.ts`), not an outer-scope variable —
  even one from `vi.hoisted()`.
- To configure or assert on a mocked function, import the real binding (`import { goto } from
  '$app/navigation'` after `vi.mock('$app/navigation', () => ({ goto: vi.fn() }))`).

### 2.4 `$env/dynamic/public` must be mocked for anything touching `$lib/net/lobby`

Any route pulling in `$lib/net/lobby` (directly, or via a child like `TableCard`) needs:

```ts
vi.mock('$env/dynamic/public', () => ({ env: {} }))
```

SvelteKit's dev/build server populates that module at request time; under Vitest it's `undefined`,
so `lobby.ts`'s `apiBaseUrl()` throws before the component renders.

## 3. Server (pytest)

No implementation-level gotchas beyond root `AGENTS.md`'s Testing section and `server/AGENTS.md`'s
Commands table. Add them here as they turn up.

- `server/tests/conftest.py` pins `SHUTDOWN_GRACE_SECONDS=0`: every `TestClient(app)` exit runs the
  real shutdown drain ([architecture.md §8.1](architecture.md)). It also zeroes
  `BOT_THINK_*_SECONDS` and `CLAIM_HOLD_SECONDS` ([architecture.md §4](architecture.md) "Claim
  hold"); `tests/test_claim_window_privacy.py` passes `claim_hold_seconds` explicitly to test it.
- CI has no Postgres; DB tests run against SQLite via the JSON/JSONB column variant
  ([infra.md §6](infra.md)).
- A helper used by more than one test module lives in a plain module under `server/tests/`,
  imported as `from tests.<module> import …`; fixtures go in `conftest.py` instead. Don't
  re-declare one locally.

| Module | Holds |
| --- | --- |
| `conftest.py` | `session` (in-memory SQLite `AsyncSession`, fresh schema), `games` |
| `game_state.py` | `with_seat(state, seat, **overrides)`, `total_tiles(state)` (tile-conservation count) |
| `hands.py` | `tile_ids(*types)` (one physical copy per occurrence), `pung`, `concealed_kong` |
| `decisions.py` | `decision_points(seed, ruleset)` (seeded random self-play, every live decision), `discard_mask` |
| `ws_frames.py` | client frame builders: `msg`, `next_id`, `hello`, `first_tile_ids(*types, count=)` |
| `game_records.py` | `fetch_latest_record(database_url)` |
| `latency.py` / `ml_synthetic.py` | `check_latency` (§1) / synthetic packed ML datasets |
