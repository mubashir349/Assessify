from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC datetime. Everything in the database is stored in UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt):
    """UTC datetime -> '2026-10-13T04:00:00Z' (or None)."""
    return dt.isoformat(timespec="seconds") + "Z" if dt else None
