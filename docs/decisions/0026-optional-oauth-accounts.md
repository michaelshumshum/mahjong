# 0026. Optional accounts via OAuth sign-in

- **Status:** Deferred
- **Date:** 2026-10-29

## Context

[ADR 0001](0001-guest-only-identity.md) cut accounts permanently: the design it replaced was
magic-link email sign-in, and email deliverability (a transactional provider, SPF/DKIM) was the
cost that priced it out. Since then, features have appeared that would want an identity:

| Want | Today | Without an account |
| --- | --- | --- |
| Learn progress across devices | `mahjong:learnProgress:v1`, local only ([ADR 0025](0025-learn-mode.md)) | lost on a new device or a cleared browser |
| Stats and a profile page | `/profile` is a placeholder | per-browser only |
| Rating, leaderboard | not built ([ADR 0003](0003-product-scope.md) post-launch list) | aggregates by display name, which anyone can type |
| Seat reclaim on another device mid-game | per-browser `reconnect_secret` | not possible |

None of these is wanted badly enough yet. A rating or leaderboard is the one that breaks without
accounts: the others degrade, but a ranking keyed by a free-typed name is meaningless.

## Design sketch

**Optional, never required.** Guest play stays the default and the fastest path: share a link,
pick a name, play. An account only adds sync and a stable identity.

**OAuth only, no email or password.** Sign-in through one or more providers removes the email
infrastructure that made ADR 0001's design expensive. Candidates:

| Provider | Why |
| --- | --- |
| Discord | the friend groups this app targets often coordinate there ([ADR 0003](0003-product-scope.md)) |
| Google | broadest reach |
| Apple | required by App Store rules only if a native app ever offers other social logins; otherwise optional |

Start with one or two; adding a provider later is a config row plus a callback route.

**Flow:** OAuth 2.0 authorization code with PKCE, handled server-side (FastAPI). The callback
upserts a `users` row keyed by `(provider, provider_subject)` and sets a session.

| Piece | Sketch |
| --- | --- |
| Session | an opaque session id in an `HttpOnly`, `Secure`, `SameSite=Lax` cookie, rows in Postgres. Not a JWT: revocation is a row delete, and nothing else needs a stateless token. `JWT_SECRET` (unused since ADR 0001) gets removed rather than revived |
| WebSocket | the cookie rides the WS handshake (same site); the server resolves it to a user before `join`. Seat possession still uses `reconnect_secret`; an account adds "this seat belongs to this user" for cross-device reclaim |
| Tables | `users(id, display_name, created_at)`, `identities(user_id, provider, subject)`, `sessions(id, user_id, expires_at)`, plus per-feature tables (`learn_progress(user_id, lesson_id, …)`) |
| Guest → account | on first sign-in, the client uploads its local progress (learn progress, display name, prefs); the server merges, solved wins |
| Display name | defaults from the provider, editable; uniqueness only matters if a leaderboard ships |
| Guest identity in game records | unchanged: records keep the display name; a signed-in seat also records `user_id` |

**Middle step that may make this unnecessary:** a *transfer code*: an export link or short code
that carries local progress and prefs to another device, with no account at all. It covers the
main Learn-mode need for roughly a day of work. Build it first if cross-device progress is asked
for and nothing needs a stable identity yet.

## Needs before reviving

- **A trigger:** a rating or leaderboard is being built, or players ask for cross-device progress
  that a transfer code doesn't satisfy.
- **A superseding decision:** reviving this reverses ADR 0001; mark 0001 superseded rather than
  editing it.
- **Privacy:** a privacy policy and an account-deletion path (delete user, identities, sessions and
  per-feature rows; anonymise `user_id` in game records). Storing a provider subject and name is
  personal data.
- **Disclosure:** if game records of signed-in players feed training ([ADR 0016](0016-human-records-as-training-data.md)), the consent line that ADR needs lands here.
- **Provider setup:** OAuth app registrations, redirect URIs per environment, client secrets in
  `.env` ([infra.md §2](../infra.md)), and the CSRF `state` parameter on the authorize step.
- **Abuse:** sign-in endpoints get per-IP rate limits like the rest of the API.
- **Protocol:** a `user` field on `state_sync` seats, or not; decide whether other players see that
  a seat is signed in.
