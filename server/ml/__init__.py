"""The only place `torch`/`numpy`/`pettingzoo` may be imported from.

`mahjong_core`, `app`, and base `bots/` (T0-T2) stay stdlib-only (see `server/AGENTS.md` and
`pyproject.toml`'s `[project.optional-dependencies] ml` comment) -- nothing outside this package
may import from `ml/`, and nothing in this package may be imported by them. Installed only via
the `ml` extra / the Dockerfile's `ml` image stage / `docker-compose.yml`'s `trainer`/`arena`
services.

Currently an empty skeleton: makes the `ml` extra, the `ml` Docker stage, and the `trainer`
service actually resolve to a real package. No encoding, no AEC wrapper, no training loop --
see docs/99-deferred.md.
"""
