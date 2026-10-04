"""Opponent-danger network (docs/ml.md §5): one (row, opponent) sample in, that opponent's
tenpai probability, per-tile legal/structural wait logits and per-tile faan class logits out.

A 1-D pre-activation ResNet over the tile axis. Tiles sit on a 37-wide axis with a zero column
between suits so a kernel never sees a false 9m-1p adjacency; pad columns are re-zeroed after
every block. `ml`-extra only (torch).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import torch
from torch import nn

from ml.encode import N_SCALARS, N_TILE_CHANNELS, N_TILE_TYPES

__all__ = ["N_FAAN_CLASSES", "DangerNet", "DangerNetConfig", "DangerOutput"]

N_FAAN_CLASSES = 10  # faan 1..10; class k is faan k + 1, higher values clip to the last class
_PADDED_WIDTH = 37


def _padded_positions() -> torch.Tensor:
    pos = [*range(9), *range(10, 19), *range(20, 29), *range(30, 37)]
    assert len(pos) == N_TILE_TYPES
    return torch.tensor(pos)


@dataclass(frozen=True)
class DangerNetConfig:
    channels: int = 96
    blocks: int = 6
    se_ratio: int = 4
    in_tiles: int = N_TILE_CHANNELS
    in_scalars: int = N_SCALARS

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class DangerOutput:
    tenpai: torch.Tensor
    legal_wait: torch.Tensor  # a wait that is a legal win under `min_faan`
    struct_wait: torch.Tensor
    faan: torch.Tensor  # (B, 34, N_FAAN_CLASSES)


class _Block(nn.Module):
    def __init__(self, ch: int, se_ratio: int) -> None:
        super().__init__()
        self.norm1 = nn.GroupNorm(8, ch)
        self.conv1 = nn.Conv1d(ch, ch, 3, padding=1)
        self.norm2 = nn.GroupNorm(8, ch)
        self.conv2 = nn.Conv1d(ch, ch, 3, padding=1)
        self.se1 = nn.Linear(ch, ch // se_ratio)
        self.se2 = nn.Linear(ch // se_ratio, ch)

    def forward(self, x: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        h = self.conv1(torch.relu(self.norm1(x)) * mask)
        h = self.conv2(torch.relu(self.norm2(h)) * mask)
        pooled = (h * mask).sum(-1) / N_TILE_TYPES
        gate = torch.sigmoid(self.se2(torch.relu(self.se1(pooled))))
        return (x + h * gate.unsqueeze(-1)) * mask


class DangerNet(nn.Module):
    def __init__(self, config: DangerNetConfig | None = None) -> None:
        super().__init__()
        self.config = config or DangerNetConfig()
        ch = self.config.channels
        self.stem = nn.Conv1d(self.config.in_tiles, ch, 3, padding=1)
        self.scalar_proj = nn.Linear(self.config.in_scalars, ch)
        self.blocks = nn.ModuleList(
            _Block(ch, self.config.se_ratio) for _ in range(self.config.blocks)
        )
        self.final_norm = nn.GroupNorm(8, ch)
        self.tile_head = nn.Conv1d(ch, 2 + N_FAAN_CLASSES, 1)
        self.tenpai_head = nn.Sequential(
            nn.Linear(2 * ch + self.config.in_scalars, ch), nn.ReLU(), nn.Linear(ch, 1)
        )
        self.register_buffer("positions", _padded_positions(), persistent=False)
        mask = torch.zeros(1, 1, _PADDED_WIDTH)
        mask[..., self.positions] = 1.0
        self.register_buffer("mask", mask, persistent=False)

    def forward(self, tiles: torch.Tensor, scalars: torch.Tensor) -> DangerOutput:
        b = tiles.shape[0]
        x = tiles.new_zeros(b, tiles.shape[1], _PADDED_WIDTH)
        x[:, :, self.positions] = tiles
        h = (self.stem(x) + self.scalar_proj(scalars).unsqueeze(-1)) * self.mask
        for block in self.blocks:
            h = block(h, self.mask)
        h = torch.relu(self.final_norm(h)) * self.mask

        per_tile = self.tile_head(h)[:, :, self.positions]  # (B, 2 + classes, 34)
        pooled = torch.cat(
            [
                h.sum(-1) / N_TILE_TYPES,
                h.masked_fill(self.mask == 0, float("-inf")).amax(-1),
                scalars,
            ],
            dim=1,
        )
        return DangerOutput(
            tenpai=self.tenpai_head(pooled).squeeze(-1),
            legal_wait=per_tile[:, 0],
            struct_wait=per_tile[:, 1],
            faan=per_tile[:, 2:].transpose(1, 2),
        )


def n_parameters(model: nn.Module) -> int:
    return sum(int(np.prod(p.shape)) for p in model.parameters())
