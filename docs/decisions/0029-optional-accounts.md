# 0029. Optional accounts (supersedes 0001)

- **Status:** Accepted
- **Date:** 2026-11-05

## Context

[ADR 0001](0001-guest-only-identity.md) cut accounts permanently. Its cost driver was magic-link
email sign-in: a transactional provider, SPF/DKIM and deliverability. [ADR 0026](0026-optional-oauth-accounts.md)
sketched an account design without email, and [ADR 0028](0028-user-account-schema.md) laid out
its schema and a phased plan. Reviving accounts reverses 0001, and 0026 asks for that reversal as
its own record rather than an edit to 0001.

## Decision

Accounts become optional, through Google OAuth sign-in only. Guests stay first-class.

| 0001 said | Now |
| --- | --- |
| Guest-only, permanently; no account | guest by default; an account is opt-in and adds game history, learn sync and a stable identity |
| No email, password, JWT or REST auth endpoint | no password, no JWT, no sign-in by email. OAuth 2.0 with PKCE (Google), an opaque session cookie with rows in Postgres, REST routes under `/auth/*` and `/me*`. Email is stored only as a contact field |
| No `users` table; names are the permanent identity | `users`, `identities`, `sessions`; a signed-in seat records `user_id` beside the name. Guest seats are unchanged |
| `JWT_SECRET` kept but unread | removed |

Unchanged from 0001: seat possession on reconnect still uses the per-browser `reconnect_secret`,
and a guest's display name is still picked client-side.

Design: [ADR 0026](0026-optional-oauth-accounts.md). Schema, decisions and PR plan:
[ADR 0028](0028-user-account-schema.md).

## Consequences

- Status stayed `Deferred` until sign-in was public (0028 phase 7, 2026-11). Then this record
  became `Accepted`, 0001 `Superseded`, and 0026 and 0028 `Accepted`.
- Sign-in stayed behind `ACCOUNTS_ENABLED` and the matching web flag until the privacy policy
  and terms shipped (`/privacy`, `/terms`). Both flags are on in prod and kept as kill switches.
- Adding a provider later is a config row and a callback route; `identities` already has the
  multi-provider shape.
