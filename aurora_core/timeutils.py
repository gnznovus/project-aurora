from __future__ import annotations

from datetime import UTC, datetime


def utc_now_naive() -> datetime:
    """Return UTC timestamp as naive datetime for timezone=False DB columns."""
    return datetime.now(UTC).replace(tzinfo=None)

