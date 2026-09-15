"""Small shared BFF utilities.

Only genuinely cross-domain mechanics live here; anything with domain
meaning stays in its domain module. (Note: SQL statements are kept as
inline literals at each execute site by project convention — the static
security tooling rejects any indirect SQL reference.)
"""

import hmac
from datetime import UTC, datetime


def utc_now() -> str:
    """Single timestamp format for every persisted lumi.sqlite timestamp."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def constant_time_equals(left: str, right: str) -> bool:
    """hmac.compare_digest over the UTF-8 bytes.

    The str variant of ``compare_digest`` raises TypeError on non-ASCII
    input, and both ASGI headers (latin-1) and URL paths (UTF-8) can
    carry non-ASCII — a hostile bearer/token value must fail the
    comparison, not 500 (Q-P1-11)."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
