# 0005. Client-contributed entropy for provable fairness

- **Status:** Deferred
- **Date:** 2026-09-14

## Context

The shipped scheme commits `SHA256(hand_seed || nonce)` at hand start and reveals it at hand end
([protocol.md §3](../protocol.md) "Fairness"). It proves the wall wasn't edited *after*
commitment, not that the deal was unbiased: the server alone picks `hand_seed` and `nonce` and
knows the resulting wall before committing, so it could grind pairs off-protocol.

## Design sketch

Each seat contributes entropy the server cannot see in advance.

1. Before the deal, each seat generates a private nonce `nᵢ` and sends `Cᵢ = SHA256(nᵢ)`.
2. Once all four commitments are in, `hand_seed = SHA256(n₀ ‖ n₁ ‖ n₂ ‖ n₃)` — computable only
   after every seat has locked in, so no party can choose its contribution after seeing another's.
3. The deal proceeds as now; `hand_seed`, not `game_seed`, is revealed at hand end.
4. At hand end each seat reveals `nᵢ`; everyone checks `SHA256(nᵢ) == Cᵢ` and recomputes
   `hand_seed`.

## Needs before reviving

- A commit round adds a network round-trip before every hand: needs a bounded timeout and a
  fallback for a seat that never sends `Cᵢ` or never reveals `nᵢ` (server-only entropy for that
  hand? forfeit and a bot substitutes?).
- Bot seats need unpredictable entropy of their own, or it reduces to the server choosing.
- Every hand, or only rated play, given the latency.
- Protocol messages for the commit/reveal round.
