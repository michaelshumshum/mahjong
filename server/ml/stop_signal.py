"""SIGINT/SIGTERM as a polled flag: a long ML job finishes its current unit of work (a train step,
a game) and exits cleanly instead of dying mid-write. Torch-free."""

from __future__ import annotations

import signal
from types import FrameType

_SIGNALS = (signal.SIGINT, signal.SIGTERM)


class StopSignal:
    """Installs itself on construction; `requested` flips on the first signal. `finishing` ends
    the log line (`received signal 15, <finishing>`)."""

    def __init__(self, finishing: str) -> None:
        self.requested = False
        self._finishing = finishing
        self._previous = {sig: signal.signal(sig, self._handle) for sig in _SIGNALS}

    def _handle(self, signum: int, _frame: FrameType | None) -> None:
        print(f"received signal {signum}, {self._finishing}", flush=True)
        self.requested = True

    def restore(self) -> None:
        """Reinstalls whatever handlers were active before this one."""
        for sig, handler in self._previous.items():
            signal.signal(sig, handler)
