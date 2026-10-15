import time


def now_ms() -> int:
    """Server epoch ms, the unit of every wire `ts`/`deadline_ts` (docs/protocol.md §4)."""
    return time.time_ns() // 1_000_000
