"""R1 exit measurements for `PolicyNet`'s auxiliary heads (docs/06-ml.md §8, §14):

    python -m ml.aux_eval --ckpt runs/rl_aux/ckpt_best.pt --data data/rl_aux_packed \
        --danger-ckpt runs/danger/ckpt_best.pt [--split test]

- **Danger.** Legal-wait AUC at candidate-discard tiles (tiles the seat holds, the v3 protocol of
  `ml.evaluate`) and tenpai AUC, on own-turn rows; with `--danger-ckpt`, `DangerNet` is scored on
  the same rows (`ml.aux_data.danger_raw`) and the paired AUC difference gets a CI.
- **Hidden tiles.** Mean negative log-likelihood, per unseen copy, of its true location (each
  opponent's concealed tiles + concealed kongs, or the live wall) against **uniform over unseen**:
  every unseen copy equally likely to sit in any hidden slot, so P(location) = that location's
  hidden-slot count / all hidden slots (public: concealed counts, concealed-kong counts, wall).
- Own win / deal-in AUC; shanten and ukeire MAE on own discard turns.

Intervals resample games (`ml.metrics.game_bootstrap`).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch

from ml.aux_data import AuxData, danger_raw
from ml.aux_train import to_tensors
from ml.encode import encode_batch
from ml.metrics import add_stats, game_bootstrap, game_stats, metric_fns
from ml.policy_net import PolicyNet, PolicyNetConfig
from ml.splits import TEST, TRAIN, VAL

__all__ = ["evaluate_aux_model", "load_policy", "main"]

_SPLITS = {"train": TRAIN, "val": VAL, "test": TEST}


def load_policy(ckpt_path: Path) -> PolicyNet:
    ckpt = torch.load(ckpt_path, weights_only=False, map_location="cpu")
    model = PolicyNet(PolicyNetConfig(**ckpt["model_config"]))
    model.load_state_dict(ckpt["model"])
    return model.eval()


def _sig(x: torch.Tensor) -> np.ndarray:
    return torch.sigmoid(x).numpy().astype(np.float64)


def _acc(acc: dict[str, Any], name: str, stats: dict[str, np.ndarray]) -> None:
    acc[name] = stats if name not in acc else add_stats(acc[name], stats)


def evaluate_aux_model(
    model: PolicyNet,
    data: AuxData,
    rows: np.ndarray,
    *,
    danger: Any = None,
    chunk: int = 2048,
    n_boot: int = 500,
    seed: int = 0,
) -> dict[str, Any]:
    seeds = np.asarray(data.raw["game_seed"])[rows]
    games, game_of = np.unique(seeds, return_inverse=True)
    n_games = len(games)
    acc: dict[str, Any] = {}
    hidden = {k: np.zeros(n_games) for k in ("model", "base", "n")}
    mae = {k: np.zeros(2) for k in ("shanten", "ukeire")}

    with torch.no_grad():
        for i in range(0, len(rows), chunk):
            idx = np.arange(i, min(i + chunk, len(rows)))
            inputs, t, raw = data.arrays(rows[idx])
            x = to_tensors(inputs)
            aux = model(x["tiles"], x["scalars"]).aux
            assert aux is not None
            g = game_of[idx]

            _acc(acc, "win", game_stats(_sig(aux.win), t["win"], g, n_games))
            _acc(acc, "deal_in", game_stats(_sig(aux.deal_in), t["deal_in"], g, n_games))

            logp = aux.hidden.log_softmax(dim=1).numpy().astype(np.float64)
            h = t["hidden"].astype(np.float64)
            slots = t["slots"].astype(np.float64)
            base = np.log(np.where(slots > 0, slots, 1.0) / slots.sum(1, keepdims=True))
            hidden["model"] += np.bincount(g, -(h * logp).sum((1, 2)), n_games)
            hidden["base"] += np.bincount(g, -(h * base[:, :, None]).sum((1, 2)), n_games)
            hidden["n"] += np.bincount(g, h.sum((1, 2)), n_games)

            m = t["shanten_mask"] > 0
            for name, scale in (("shanten", 1.0), ("ukeire", 10.0)):
                err = np.abs(getattr(aux, name).numpy() - t[name]) * scale
                mae[name] += (err[m].sum(), m.sum())

            own = raw["own_turn"] > 0
            if not own.any():
                continue
            go = g[own]
            hand = (raw["concealed"] + raw["melds"][:, 0])[own] > 0
            cand = np.broadcast_to(hand[:, None], (int(own.sum()), 3, 34))
            g_tiles = np.broadcast_to(go[:, None, None], cand.shape)
            legal_y = t["legal"][own]
            scorers = {"policy": (_sig(aux.legal_wait)[own], _sig(aux.tenpai)[own])}
            if danger is not None:
                sub = {k: v[own] for k, v in danger_raw(raw).items()}
                b = int(own.sum())
                opp = np.tile(np.arange(3), b)
                rep = {k: np.repeat(v, 3, axis=0) for k, v in sub.items()}
                d_tiles, d_scalars = encode_batch(rep, opp, data.danger_ruleset_vec)
                d = danger(torch.from_numpy(d_tiles), torch.from_numpy(d_scalars))
                scorers["danger"] = (
                    _sig(d.legal_wait).reshape(b, 3, 34),
                    _sig(d.tenpai).reshape(b, 3),
                )
            for name, (lw, tp) in scorers.items():
                stats = game_stats(lw[cand], legal_y[cand], g_tiles[cand], n_games)
                _acc(acc, f"{name}_legal_wait", stats)
                gt = np.broadcast_to(go[:, None], tp.shape).ravel()
                _acc(
                    acc,
                    f"{name}_tenpai",
                    game_stats(tp.ravel(), t["tenpai"][own].ravel(), gt, n_games),
                )

    auc = metric_fns["auc"]
    result: dict[str, Any] = {"n_rows": len(rows), "n_games": n_games}
    for name, stats in acc.items():
        result[f"{name}_auc"] = game_bootstrap({"m": stats}, lambda s: auc(s["m"]), n_boot, seed)
    if danger is not None:
        for head in ("legal_wait", "tenpai"):
            pair = {"p": acc[f"policy_{head}"], "d": acc[f"danger_{head}"]}
            result[f"{head}_auc_policy_minus_danger"] = game_bootstrap(
                pair, lambda s: auc(s["p"]) - auc(s["d"]), n_boot, seed
            )
    hs = {"h": {k: v for k, v in hidden.items()}}
    result["hidden_nll_model"] = game_bootstrap(
        hs, lambda s: float(s["h"]["model"].sum() / s["h"]["n"].sum()), n_boot, seed
    )
    result["hidden_nll_uniform"] = game_bootstrap(
        hs, lambda s: float(s["h"]["base"].sum() / s["h"]["n"].sum()), n_boot, seed
    )
    result["hidden_nll_gain"] = game_bootstrap(
        hs,
        lambda s: float((s["h"]["base"].sum() - s["h"]["model"].sum()) / s["h"]["n"].sum()),
        n_boot,
        seed,
    )
    for name, (total, count) in mae.items():
        result[f"{name}_mae"] = float(total / max(count, 1))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ml.aux_eval", description=__doc__)
    parser.add_argument("--ckpt", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--danger-ckpt", type=Path)
    parser.add_argument("--split", choices=[*_SPLITS, "all"], default="test")
    parser.add_argument("--max-rows", type=int)
    parser.add_argument("--n-boot", type=int, default=500)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--out", type=Path)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    torch.set_num_threads(args.threads)
    data = AuxData(args.data)
    rows = (
        np.arange(data.meta["rows"]) if args.split == "all" else data.rows_of(_SPLITS[args.split])
    )
    if args.max_rows is not None and args.max_rows < len(rows):
        rows = np.sort(np.random.default_rng(0).choice(rows, args.max_rows, replace=False))
    danger = None
    if args.danger_ckpt is not None:
        from ml.evaluate import load_model

        danger = load_model(args.danger_ckpt)
    result = evaluate_aux_model(
        load_policy(args.ckpt), data, rows, danger=danger, n_boot=args.n_boot
    )
    text = json.dumps(result, indent=2)
    if args.out:
        args.out.write_text(text)
    print(text)


if __name__ == "__main__":
    main(sys.argv[1:])
