"""Admin API — account lifecycle for the operator (0067, O146/O151/O152).

FIX-161 / ARCH-01: the former 1400-line ``routers/admin.py`` monolith is
split into a package with one module per responsibility:

- ``invites`` — invitation lifecycle, invite schemes (N001), invite
  funnel (N004), FreshRSS account pool (O155/N003), capacity (N192);
- ``users`` — step-up minting (N009), user listing, pause/resume
  (O152), owner-only role provisioning, session revocation, password
  reset (O150), quota policy packages (N191), background pause (N193);
- ``audit`` — the minimal audit-trail read;
- ``ops`` — P11 system diagnostics, public-registration policy,
  upgrade preview (N195), deploy status (N196), rollback readiness
  (N197);
- ``_common`` — the shared guards/helpers every slice imports.

Scope of admin power (deliberately minimal, O151):
- create / revoke invitations (signup + recovery kinds);
- save invite schemes (N001) and batch-generate invites from them;
- read the invite funnel (N004 — counts only, never invite codes);
- list users, pause / resume members (never the owner; never the last
  active admin);
- provision roles — owner-only: grant / revoke the admin role (never
  the owner's own role; never the last active admin);
- revoke a member's sessions;
- register FreshRSS pool accounts (deployment-side CLI creates them;
  this API only registers the binding material);
- read the minimal audit trail.

Admins have NO route to read another user's business content — feeds,
entries, library, AI sessions stay private. 403 shapes are stable; the
audit log records lifecycle actions (never credentials).

Contract invariants (pinned by tests/test_fix161_admin_router_split.py):
route paths, methods, endpoint function names (they derive the OpenAPI
``operationId``) and the request/response models are byte-identical to
the pre-split module — ``pnpm api:check`` must stay green. The shared
guard names that other route modules (new304/37x/399) and tests import
from ``lumirss.routers.admin`` are re-exported below.
"""

from fastapi import APIRouter

from lumirss.routers.admin._common import (  # noqa: F401  (re-exported)
    _NO_STORE,
    _accounts,
    _forbid,
    _iso,
    _parse_iso_epoch,
    _require_admin,
    _require_owner,
)
from lumirss.routers.admin.audit import router as _audit_router
from lumirss.routers.admin.invites import router as _invites_router
from lumirss.routers.admin.ops import (  # noqa: F401  (re-exported)
    _probe_freshness,
)
from lumirss.routers.admin.ops import router as _ops_router
from lumirss.routers.admin.users import router as _users_router

router = APIRouter(prefix="/api/v1/admin")
# Registration order mirrors the former monolith's section order
# (users-security first, then invites/pool, audit, ops). The admin path
# space is disjoint, so ordering is documentation, not semantics.
router.include_router(_users_router)
router.include_router(_invites_router)
router.include_router(_audit_router)
router.include_router(_ops_router)
