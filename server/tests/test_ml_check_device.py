"""`ml/check_device.py` runs end to end on a CPU-only machine (docs/06-ml.md §13)."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from ml.check_device import main


def test_check_device_reports_cpu_and_skips_missing_cuda(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    out = tmp_path / "report.json"
    small = ["--envs", "4", "--workers", "0", "--batch-size", "64", "--channels", "8"]
    report = main(
        [*small, "--blocks", "1", "--bench-updates", "1", "--act-steps", "2", "--updates", "2"]
        + ["--json", str(out)]
    )
    assert "skipping cuda" in capsys.readouterr().out
    assert report["environment"]["cuda_available"] is False
    assert list(report["devices"]) == ["cpu"]
    assert report["learner"]["cpu"]["learner_decisions_per_s"] > 0
    assert report["end_to_end"]["cpu"]["updates"] == 2
    assert report["end_to_end"]["cpu"]["decisions_per_s"] > 0
    assert json.loads(out.read_text())["config"]["envs"] == 4


def test_amp_only_applies_to_cuda_devices(tmp_path, monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    small = ["--envs", "4", "--workers", "0", "--batch-size", "64", "--channels", "8"]
    report = main(
        [*small, "--blocks", "1", "--bench-updates", "1", "--act-steps", "2"]
        + ["--updates", "1", "--amp"]
    )
    assert report["config"]["amp"] is True
    assert report["learner"]["cpu"]["amp"] is False
    assert report["end_to_end"]["cpu"]["updates"] == 1


def test_driver_falls_back_to_the_wsl_nvidia_smi(tmp_path, monkeypatch):
    import ml.check_device as cd

    fake = tmp_path / "nvidia-smi"
    fake.write_text("#!/bin/sh\necho 610.88\n")
    fake.chmod(0o755)
    monkeypatch.setattr(cd.shutil, "which", lambda name: None)
    monkeypatch.setattr(cd, "_WSL_NVIDIA_SMI", str(fake))
    assert cd._driver() == "610.88"
