"""RL policy network, oracle critic and auxiliary heads (docs/06-ml.md §8). `ml`-extra only.

`PolicyNet` is a `DangerNet`-style trunk over encoder v2's policy tensors. Its policy head is
tile-equivariant: a 1x1 conv gives 3 logits per tile (discard / concealed kong / added kong), laid
out as action ids 0..101 exactly as `mahjong_core.ml` does, plus a 7-way global head for ids
102..108 (pass, chow low/middle/high, pung, kong, win). The global head also reads the trunk's
features at the claimable tile, so the relative chow ids see which tile is up for claim.

`OracleCritic` is a separate trunk over policy + oracle tensors that outputs a value; it is
training-only and never exported. Auxiliary heads hang off the policy trunk and are dropped at
export too: only `trunk.*` and `policy_*` serve.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import torch
from torch import nn

from mahjong_core.ml import N_ACTIONS
from ml.danger_model import _PADDED_WIDTH, N_FAAN_CLASSES, _Block, _padded_positions
from ml.encode import N_TILE_TYPES
from ml.encode_v2 import N_ORACLE_CHANNELS, N_POLICY_CHANNELS, N_POLICY_SCALARS, POLICY_CHANNELS

__all__ = [
    "CLAIM_CHANNEL",
    "GLOBAL_ACTIONS",
    "N_HIDDEN_LOCATIONS",
    "N_TILE_ACTION_KINDS",
    "AuxOutput",
    "OracleCritic",
    "PolicyNet",
    "PolicyNetConfig",
    "PolicyOutput",
    "Trunk",
    "assemble_logits",
    "logit_source",
    "masked_entropy",
    "masked_log_softmax",
    "n_parameters",
]

N_TILE_ACTION_KINDS = 3
GLOBAL_ACTIONS = ("pass", "chow_low", "chow_middle", "chow_high", "pung", "kong", "win")
N_HIDDEN_LOCATIONS = 4  # next, across, previous opponent, live wall
CLAIM_CHANNEL = POLICY_CHANNELS["claimable"].start
_OPP = 3
# aux tile-conv channel layout
_AUX_TILE = (
    ("legal_wait", _OPP),
    ("struct_wait", _OPP),
    ("faan", _OPP * N_FAAN_CLASSES),
    ("hidden", N_HIDDEN_LOCATIONS),
    ("shanten", 1),
    ("ukeire", 1),
)
_AUX_GLOBAL = (("tenpai", _OPP), ("win", 1), ("deal_in", 1), ("points", 1))


def _slices(layout: tuple[tuple[str, int], ...]) -> dict[str, slice]:
    out, at = {}, 0
    for name, n in layout:
        out[name] = slice(at, at + n)
        at += n
    return out


_AUX_TILE_SLICES = _slices(_AUX_TILE)
_AUX_GLOBAL_SLICES = _slices(_AUX_GLOBAL)


@dataclass(frozen=True)
class PolicyNetConfig:
    channels: int = 96
    blocks: int = 6
    se_ratio: int = 4
    in_tiles: int = N_POLICY_CHANNELS
    in_scalars: int = N_POLICY_SCALARS

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


class Trunk(nn.Module):
    """`DangerNet`'s trunk: stem conv + scalar bias, pre-activation SE blocks, final norm, on the
    37-wide padded tile axis. Returns `(B, channels, 37)` with pad columns zero."""

    def __init__(self, in_tiles: int, in_scalars: int, channels: int, blocks: int, se: int) -> None:
        super().__init__()
        self.stem = nn.Conv1d(in_tiles, channels, 3, padding=1)
        self.scalar_proj = nn.Linear(in_scalars, channels)
        self.blocks = nn.ModuleList(_Block(channels, se) for _ in range(blocks))
        self.final_norm = nn.GroupNorm(8, channels)
        self.register_buffer("positions", _padded_positions(), persistent=False)
        mask = torch.zeros(1, 1, _PADDED_WIDTH)
        mask[..., self.positions] = 1.0
        self.register_buffer("mask", mask, persistent=False)

    def forward(self, tiles: torch.Tensor, scalars: torch.Tensor) -> torch.Tensor:
        x = tiles.new_zeros(tiles.shape[0], tiles.shape[1], _PADDED_WIDTH)
        x[:, :, self.positions] = tiles
        h = (self.stem(x) + self.scalar_proj(scalars).unsqueeze(-1)) * self.mask
        for block in self.blocks:
            h = block(h, self.mask)
        return torch.relu(self.final_norm(h)) * self.mask

    def pooled(self, h: torch.Tensor, scalars: torch.Tensor) -> torch.Tensor:
        """`(B, 2 * channels + S)`: mean and max over real tile columns, then the scalars."""
        return torch.cat(
            [
                h.sum(-1) / N_TILE_TYPES,
                h.masked_fill(self.mask == 0, float("-inf")).amax(-1),
                scalars,
            ],
            dim=1,
        )


@dataclass(frozen=True)
class AuxOutput:
    """Opponent axes are next/across/previous. `tenpai (B, 3)`, `legal_wait`/`struct_wait`
    `(B, 3, 34)`, `faan (B, 3, 34, N_FAAN_CLASSES)` logits; `win`/`deal_in (B,)` logits for this
    seat winning / feeding the win; `points (B,)` E[payment / 32 | win]; `hidden (B, 4, 34)`
    location logits per unseen copy (3 opponents, live wall); `shanten`/`ukeire (B, 34)` after
    discarding that tile, ukeire / 10."""

    tenpai: torch.Tensor
    legal_wait: torch.Tensor
    struct_wait: torch.Tensor
    faan: torch.Tensor
    win: torch.Tensor
    deal_in: torch.Tensor
    points: torch.Tensor
    hidden: torch.Tensor
    shanten: torch.Tensor
    ukeire: torch.Tensor


@dataclass(frozen=True)
class PolicyOutput:
    logits: torch.Tensor  # (B, N_ACTIONS), unmasked
    aux: AuxOutput | None


def assemble_logits(tile_logits: torch.Tensor, global_logits: torch.Tensor) -> torch.Tensor:
    """`(B, 3, 34)` per-tile + `(B, 7)` global -> `(B, 109)` in `mahjong_core.ml` id order."""
    return torch.cat([tile_logits.flatten(1), global_logits], dim=1)


def logit_source(aid: int) -> tuple[str, int, int]:
    """Where `assemble_logits` takes action id `aid` from: `("tile", kind, tile_type)` or
    `("global", index, -1)`."""
    if not 0 <= aid < N_ACTIONS:
        raise ValueError(f"action id out of range: {aid}")
    if aid < N_TILE_ACTION_KINDS * N_TILE_TYPES:
        kind, t = divmod(aid, N_TILE_TYPES)
        return ("tile", kind, t)
    return ("global", aid - N_TILE_ACTION_KINDS * N_TILE_TYPES, -1)


def masked_log_softmax(logits: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """Log-probabilities over legal ids only; illegal ids are `-inf`. Every row needs at least
    one legal id."""
    return logits.masked_fill(~mask, float("-inf")).log_softmax(-1)


def masked_entropy(logp: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """Entropy of the masked distribution; illegal ids contribute 0, not `nan`."""
    # masked_fill before the product: where() would still backprop 0 * -inf = nan
    return -(logp.exp() * logp.masked_fill(~mask, 0.0)).sum(-1)


class PolicyNet(nn.Module):
    def __init__(self, config: PolicyNetConfig | None = None) -> None:
        super().__init__()
        self.config = c = config or PolicyNetConfig()
        ch = c.channels
        self.trunk = Trunk(c.in_tiles, c.in_scalars, ch, c.blocks, c.se_ratio)
        self.policy_tile = nn.Conv1d(ch, N_TILE_ACTION_KINDS, 1)
        self.policy_global = nn.Sequential(
            nn.Linear(3 * ch + c.in_scalars, ch), nn.ReLU(), nn.Linear(ch, len(GLOBAL_ACTIONS))
        )
        self.aux_tile = nn.Conv1d(ch, sum(n for _, n in _AUX_TILE), 1)
        self.aux_global = nn.Sequential(
            nn.Linear(2 * ch + c.in_scalars, ch),
            nn.ReLU(),
            nn.Linear(ch, sum(n for _, n in _AUX_GLOBAL)),
        )

    def forward(
        self, tiles: torch.Tensor, scalars: torch.Tensor, *, aux: bool = True
    ) -> PolicyOutput:
        trunk = self.trunk
        h = trunk(tiles, scalars)
        h_tiles = h[:, :, trunk.positions]  # (B, ch, 34)
        pooled = trunk.pooled(h, scalars)
        claim = torch.einsum("bct,bt->bc", h_tiles, tiles[:, CLAIM_CHANNEL])
        tile_logits = self.policy_tile(h_tiles)
        global_logits = self.policy_global(torch.cat([pooled, claim], dim=1))
        logits = assemble_logits(tile_logits, global_logits)
        return PolicyOutput(logits, self._aux(h_tiles, pooled) if aux else None)

    def _aux(self, h_tiles: torch.Tensor, pooled: torch.Tensor) -> AuxOutput:
        t = self.aux_tile(h_tiles)
        g = self.aux_global(pooled)
        ts, gs = _AUX_TILE_SLICES, _AUX_GLOBAL_SLICES
        b = t.shape[0]
        faan = t[:, ts["faan"]].reshape(b, _OPP, N_FAAN_CLASSES, N_TILE_TYPES)
        return AuxOutput(
            tenpai=g[:, gs["tenpai"]],
            legal_wait=t[:, ts["legal_wait"]],
            struct_wait=t[:, ts["struct_wait"]],
            faan=faan.transpose(2, 3),
            win=g[:, gs["win"]].squeeze(1),
            deal_in=g[:, gs["deal_in"]].squeeze(1),
            points=g[:, gs["points"]].squeeze(1),
            hidden=t[:, ts["hidden"]],
            shanten=t[:, ts["shanten"]].squeeze(1),
            ukeire=t[:, ts["ukeire"]].squeeze(1),
        )


class OracleCritic(nn.Module):
    """V(full state): its own trunk over policy tiles + oracle tiles. Training-only."""

    def __init__(self, config: PolicyNetConfig | None = None) -> None:
        super().__init__()
        base = config or PolicyNetConfig()
        self.config = PolicyNetConfig(
            channels=base.channels,
            blocks=base.blocks,
            se_ratio=base.se_ratio,
            in_tiles=base.in_tiles + N_ORACLE_CHANNELS,
            in_scalars=base.in_scalars,
        )
        c = self.config
        self.trunk = Trunk(c.in_tiles, c.in_scalars, c.channels, c.blocks, c.se_ratio)
        self.value = nn.Sequential(
            nn.Linear(2 * c.channels + c.in_scalars, c.channels),
            nn.ReLU(),
            nn.Linear(c.channels, 1),
        )

    def forward(
        self, tiles: torch.Tensor, oracle: torch.Tensor, scalars: torch.Tensor
    ) -> torch.Tensor:
        h = self.trunk(torch.cat([tiles, oracle], dim=1), scalars)
        return self.value(self.trunk.pooled(h, scalars)).squeeze(-1)


def n_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())
