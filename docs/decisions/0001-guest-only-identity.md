# 0001. Guest-only identity

- **Status:** Accepted
- **Date:** 2026-09

## Context

The original multiplayer plan was guest-first with an optional account upgrade: REST-issued
short-lived tickets for the WS handshake, JWTs, and magic-link email sign-in. That was the one
multiplayer line item pulling in infrastructure unlike anything else in the project — email
deliverability, SPF/DKIM, a transactional provider — and it priced the multiplayer milestone at
3–4 weeks instead of 1–2.

An earlier guest design also had a seat-hijack hole: any `hello{seat}` reclaimed that seat
outright, so a second browser, or a client guessing a live seat number 0-3, could silently steal a
seat mid-game.

## Decision

Guest-only, permanently — cut, not deferred. No account, password, email, JWT or REST auth
endpoint.

- A player picks a display name client-side, persisted in `localStorage`, sent once on `join`.
- Seat *choice* stays client-asserted: `join{seat: 2}` is trusted at face value.
- Seat *possession* on reconnect is verified: `join`'s ack returns a one-time `reconnect_secret`
  that every later `hello{seat, secret}` must present ([architecture.md §2.1](../architecture.md)).
- Guest names are the permanent identity in game records and any future leaderboard.

## Consequences

- No `users` table; a leaderboard, if built, aggregates by name.
- Losing `localStorage` (new device, private tab) loses the seat. Accepted for a no-stakes game.
- `JWT_SECRET` remains in `.env.example` and both Compose files but nothing reads it.
- Revisit only if real accounts become a goal. The parked design for that is
  [ADR 0026](0026-optional-oauth-accounts.md): optional, OAuth-only sign-in, no email.
