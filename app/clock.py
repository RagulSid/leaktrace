"""Server clock. Timestamps the engine writes (audit, leases, approvals, readings received) come from here."""

import threading
import time

_lock = threading.Lock()
_last_ns = 0


def now() -> float:
    """Wall-clock seconds."""
    return time.time()


def next_ns() -> int:
    """Wall-clock nanoseconds, strictly increasing within this process (Windows clocks tick coarsely).
    Used to order episodes and audit records that are written within the same clock tick."""
    global _last_ns
    with _lock:
        _last_ns = max(time.time_ns(), _last_ns + 1)
        return _last_ns
