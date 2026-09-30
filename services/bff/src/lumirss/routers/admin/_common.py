"""Shared admin-surface plumbing (FIX-161 split).

Guards and small helpers used by every ``routers/admin/*`` module —
moved verbatim from the former ``routers/admin.py`` monolith. Route
modules import from here; the package ``__init__`` re-exports the names
other route modules (new304/37x/399) and tests already import from
``lumirss.routers.admin``.
"""

from datetime import UTC, datetime

from fastapi import Request
from fastapi.responses import JSONResponse

from lumirss.accounts_store import AccountsStore
from lumirss.user_scope import principal_of

_NO_STORE = {"Cache-Control": "no-store"}


def _accounts(request: Request) -> AccountsStore:
    return AccountsStore(request.app.state.control_db)


def _forbid(message: str = "Administrator role required.") -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"error": {"type": "forbidden", "message": message}},
        headers=_NO_STORE,
    )


async def _require_admin(request: Request) -> dict[str, str] | None:
    """Server-verified principal with an admin role (never body data)."""
    principal = principal_of(request.scope)
    if principal is None or principal.get("role") not in ("owner", "admin"):
        return None
    return principal


def _require_owner(request: Request) -> dict[str, str] | None:
    """Server-verified principal with the OWNER role.

    Role provisioning is deliberately stricter than the rest of the admin
    surface: an admin must never be able to mint another admin (or demote
    one) — power over roles belongs to the operator alone."""
    principal = principal_of(request.scope)
    if principal is None or principal.get("role") != "owner":
        return None
    return principal


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat(timespec="seconds")


def _parse_iso_epoch(value: str) -> int | None:
    """ISO-8601 → epoch seconds (naive input treated as UTC); None when
    blank. Raises ValueError on unparseable input — a stable 400, never
    a silent mis-scheduled invite."""
    text = value.strip()
    if not text:
        return None
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp())
