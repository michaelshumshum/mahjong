import os
import signal

import pytest

from ml.stop_signal import StopSignal


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_signal_sets_requested_and_restore_reinstalls_previous(
    sig: signal.Signals, capsys: pytest.CaptureFixture[str]
) -> None:
    before = signal.getsignal(sig)
    stop = StopSignal("saving after this step")
    try:
        assert not stop.requested
        os.kill(os.getpid(), sig)
        assert stop.requested
        assert f"received signal {int(sig)}, saving after this step" in capsys.readouterr().out
    finally:
        stop.restore()
    assert signal.getsignal(sig) is before
