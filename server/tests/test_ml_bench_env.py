"""`ml/bench_env.py`: the throughput benchmark runs both legs and both env flavours."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("numpy")

from ml.bench_env import bench, main


@pytest.mark.parametrize("workers", [0, 2])
@pytest.mark.parametrize("encode", [False, True])
def test_bench_reports_decisions(workers, encode):
    result = bench(4, 30, workers=workers, encode=encode)
    assert result["decisions"] == 120
    assert result["decisions_per_s"] > 0
    assert result["leg"] == ("engine+encode" if encode else "engine")


def test_main_prints_both_legs(capsys):
    main(["--envs", "2", "--steps", "5"])
    lines = capsys.readouterr().out.strip().splitlines()
    assert [json.loads(line)["leg"] for line in lines] == ["engine", "engine+encode"]
