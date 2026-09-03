"""core/clock.py — Injectable clock for testing."""
import time

_now_fn = time.time


def now() -> int:
    """Current timestamp as integer seconds."""
    return int(_now_fn())


def set_clock(fn):
    """Override clock function (tests only)."""
    global _now_fn
    _now_fn = fn


def reset_clock():
    """Restore system clock."""
    global _now_fn
    _now_fn = time.time
