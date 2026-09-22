"""Machine-channel (bearer) authentication helpers (0067).

Feed / ingest bearers arrive WITHOUT a browser session. The auth
middlewares defer those requests to the route boundary; the route uses
:meth:`machine_user_context` to resolve the token's owner from the
control ``token_owner_index`` and enter that user's data scope.

Security properties:
- the raw token is hashed before the index lookup (the index stores
  hashes only);
- an unknown token yields ``None`` — the caller replies with the same
  404 as a wrong secret, so existence never leaks;
- basic (legacy single-user) mode always runs under the owner context
  the middleware already set, so legacy deployments keep working.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Request

from lumirss.accounts_store import AccountsStore, hash_token
from lumirss.config import LumiSettings
from lumirss.user_scope import current_user_id, user_context


@asynccontextmanager
async def machine_user_context(request: Request, supplied_token: str) -> AsyncIterator[str | None]:
    """Enter the owning user's scope for a bearer machine call.

    Yields the user id the rest of the request must run under, or None
    when the token is unknown in session mode — callers MUST treat None
    as an authentication failure (404 with no existence oracle).
    """
    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        yield current_user_id()
        return
    if not supplied_token:
        yield None
        return
    uid = await AccountsStore(request.app.state.control_db).token_owner(
        hash_token(supplied_token)
    )
    if uid is None:
        yield None
        return
    with user_context(uid):
        yield uid


async def index_machine_token(request: Request, raw_token: str, purpose: str) -> None:
    """Record a freshly minted bearer token's owner (creation/rotation).

    Runs inside the creating user's session, so the owner is the
    server-verified principal — never client input.
    """
    principal = request.scope.get("lumi_principal")
    if principal is None:
        return
    await AccountsStore(request.app.state.control_db).index_token(
        hash_token(raw_token), principal["user_id"], purpose
    )


async def resolve_machine_user(request: Request, supplied_token: str) -> str | None:
    """Bind the token owner's scope for the rest of the request task.

    Same contract as :func:`machine_user_context` for long route bodies:
    returns the resolved user id (context bound in place) or None —
    callers must treat None as authentication failure (404, no oracle).
    """
    from lumirss.config import LumiSettings
    from lumirss.user_scope import bind_user_context

    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return current_user_id()
    if not supplied_token:
        return None
    uid = await AccountsStore(request.app.state.control_db).token_owner(
        hash_token(supplied_token)
    )
    if uid is None:
        return None
    bind_user_context(uid)
    return uid
