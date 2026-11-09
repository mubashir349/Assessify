"""Phase 8: counts wrong login tries and refuses more than `limit` inside `window` seconds (429 TOO_MANY_ATTEMPTS).

Used by the admin login and the candidate login. The counters live in this process's memory: enough for one server
process (waitress runs one process with many threads). Several processes would need a shared store such as Redis.
"""
import threading
import time

from app.common.errors import ApiError

_lock = threading.Lock()
_fails: dict[str, list[float]] = {}          # "admin-email:x@y" / "candidate-ip:1.2.3.4" -> times of recent failures


def _recent(key: str, window: int, now: float) -> list[float]:
    times = [t for t in _fails.get(key, []) if now - t < window]
    if times:
        _fails[key] = times
    else:
        _fails.pop(key, None)
    return times


def check(keys: list[tuple[str, int]], window: int, message: str) -> None:
    """Raise 429 when any key already has `limit` failures inside the window. message gets the minutes to wait."""
    now = time.monotonic()
    with _lock:
        for key, limit in keys:
            times = _recent(key, window, now)
            if len(times) >= limit:
                wait = int(window - (now - times[0])) + 1
                raise ApiError("TOO_MANY_ATTEMPTS", message.format(minutes=max(1, round(wait / 60))), 429,
                               {"retry_after": wait})


def record_failure(keys: list[tuple[str, int]]) -> None:
    now = time.monotonic()
    with _lock:
        for key, _ in keys:
            _fails.setdefault(key, []).append(now)


def clear(keys: list[tuple[str, int]]) -> None:
    """A successful login forgets that key's earlier failures."""
    with _lock:
        for key, _ in keys:
            _fails.pop(key, None)


def reset() -> None:
    with _lock:
        _fails.clear()
