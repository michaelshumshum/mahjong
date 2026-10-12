"""The only place `torch` may be imported from; `numpy` too, bar `bots/learned.py`.

`mahjong_core`, `app`, and `bots/` T0-T2 stay stdlib-only (see `server/AGENTS.md`). The one
exception is the served policy: `bots/learned.py` (`T4`) imports the torch-free modules
`ml.raw`, `ml.encode`, `ml.encode_v2` and `ml.export`, numpy being a base dependency for it.
Nothing outside this package imports any other `ml/` module, and those four never import torch
(`tests/test_learned_bot.py`). torch is installed only via the `ml` extra / the Dockerfile's `ml`
image stage / `docker-compose.yml`'s `trainer`/`arena` services.

Self-play RL agent and the supervised pieces it reuses: docs/ml.md.
"""
