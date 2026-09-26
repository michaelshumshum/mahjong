"""CLI entry point: `python -m ml.train --config ml/configs/bc.yaml` (docker-compose.yml's
`trainer` service, this repo's `make train`).

Stub only. `--help` works and exits 0 -- that's what the `ml` Docker image's CMD and the CI ml
smoke test both check. Passing a real `--config` fails loudly instead of silently no-op'ing:
there is no encoder, no PettingZoo AEC wrapper, and no training loop yet. See docs/99-deferred.md
("Feature-plane encoding", "PettingZoo AEC environment wrapper", "Behaviour cloning from
FaanBot", "Self-play PPO + batched inference serving") for what's missing and why it's deferred.
"""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ml.train",
        description="Train a policy from self-play / behaviour-cloning data. Not implemented yet.",
    )
    parser.add_argument(
        "--config",
        required=True,
        help="path to a training config yaml, e.g. ml/configs/bc.yaml",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    raise NotImplementedError(
        f"ml.train is a stub -- no encoder, AEC wrapper, or training loop exists yet "
        f"(config={args.config!r}). See docs/99-deferred.md for what's deferred and why."
    )


if __name__ == "__main__":
    main()
