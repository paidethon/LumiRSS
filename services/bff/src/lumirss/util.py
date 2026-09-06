"""Small shared BFF utilities.

Only genuinely cross-domain mechanics live here; anything with domain
meaning stays in its domain module. (Note: SQL statements are kept as
inline literals at each execute site by project convention — the static
security tooling rejects any indirect SQL reference.)
"""

from datetime import UTC, datetime


def utc_now() -> str:
    """Single timestamp format for every persisted lumi.sqlite timestamp."""
    return datetime.now(UTC).isoformat(timespec="seconds")
