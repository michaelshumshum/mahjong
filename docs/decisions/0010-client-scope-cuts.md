# 0010. Client features cut from scope

- **Status:** Deferred
- **Date:** 2026-09

## Context

The frontend audit that settled DOM rendering ([ADR 0002](0002-dom-rendering.md)) also trimmed
client features that weren't needed to ship. None were rejected on merit.

## Items

| Feature | Original intent | Why cut | Revisit as |
| --- | --- | --- | --- |
| Faan preview on hover | shanten, wait count, and whether the hand can reach the 3-faan minimum, for a hovered discard; gated behind a training-mode setting for rated play | no protocol message carries shanten/ukeire, and a TypeScript reimplementation would duplicate the pure Python engine | a rate-limited, debounced server `hint` request reusing `mahjong_core.shanten`/`ukeire` — not a stream: hover-rate polling would collide with intent rate limiting |
| Recorded Cantonese call-outs | 「碰」「上」「槓」「食糊」 audio | unbudgeted content task, not a code task; nobody has recorded it | — |
| High-contrast tile theme system | switchable themes | more surface than needed; the colourblind-safe dragon glyph is a fixed asset and ships regardless | — |
| Drag-to-reorder hand | sticky manual order per session | extra interaction and persistence surface; auto-sort covers finding tiles fast | — |
