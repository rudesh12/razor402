"""core/ids.py — UUID7 time-sortable ID generation."""
import uuid
import time
import os


def uuid7() -> str:
    """Generate a time-sortable UUID v7."""
    # UUID v7: unix_ts_ms (48 bits) | ver (4) | rand_a (12) | var (2) | rand_b (62)
    timestamp_ms = int(time.time() * 1000)
    rand_bytes = os.urandom(10)

    # Construct the 128-bit UUID
    time_hi = (timestamp_ms >> 16) & 0xFFFFFFFF
    time_mid = timestamp_ms & 0xFFFF

    # Random bits
    rand_a = int.from_bytes(rand_bytes[:2], "big") & 0x0FFF  # 12 bits
    rand_b = int.from_bytes(rand_bytes[2:], "big") & 0x3FFFFFFFFFFFFFFF  # 62 bits

    # Build the UUID
    hi = (time_hi << 32) | (time_mid << 16) | (0x7 << 12) | rand_a
    lo = (0b10 << 62) | rand_b

    u = uuid.UUID(int=(hi << 64) | lo)
    return str(u)
