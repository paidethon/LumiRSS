"""FIX-161 / ARCH-01: admin router split by responsibility.

The 1400-line ``routers/admin.py`` monolith is split into a
``routers/admin/`` package with one module per responsibility
(users / invites / audit / ops) plus the shared guards. The contract is
pinned from the OLD module so the split cannot drift it:

- every historical admin path + method is still served exactly (read
  from ``app.openapi()`` — the same document ``pnpm api:check`` guards);
- each submodule owns a disjoint slice of that set;
- the shared names other route modules already import
  (``_NO_STORE``/``_require_admin``/``_probe_freshness``/``_iso`` …)
  remain importable from ``lumirss.routers.admin``;
- endpoint function names are unchanged (FastAPI derives OpenAPI
  ``operationId`` from them — a rename would drift the generated
  contract checked by ``pnpm api:check``).
"""

import importlib

from fastapi.routing import APIRoute

from lumirss.main import app

ADMIN_PREFIX = "/api/v1/admin"

# The historical admin surface (path → methods), taken from the
# pre-split module. Literal on purpose: any drift fails here.
HISTORICAL_ADMIN_SURFACE: dict[str, set[str]] = {
    f"{ADMIN_PREFIX}/step-up": {"POST"},
    f"{ADMIN_PREFIX}/users": {"GET"},
    f"{ADMIN_PREFIX}/invites": {"POST", "GET"},
    f"{ADMIN_PREFIX}/invites/{{invite_id}}": {"DELETE"},
    f"{ADMIN_PREFIX}/invite-schemes": {"GET", "POST"},
    f"{ADMIN_PREFIX}/invite-schemes/{{scheme_id}}": {"DELETE"},
    f"{ADMIN_PREFIX}/invite-schemes/{{scheme_id}}/generate-invites": {"POST"},
    f"{ADMIN_PREFIX}/invite-funnel": {"GET"},
    f"{ADMIN_PREFIX}/users/{{user_id}}/pause": {"POST"},
    f"{ADMIN_PREFIX}/users/{{user_id}}/resume": {"POST"},
    f"{ADMIN_PREFIX}/users/{{user_id}}/role": {"POST"},
    f"{ADMIN_PREFIX}/users/{{user_id}}/revoke-sessions": {"POST"},
    f"{ADMIN_PREFIX}/users/{{user_id}}/reset-password": {"POST"},
    f"{ADMIN_PREFIX}/pool": {"GET", "POST"},
    f"{ADMIN_PREFIX}/audit": {"GET"},
    f"{ADMIN_PREFIX}/system": {"GET"},
    f"{ADMIN_PREFIX}/registration-policy": {"GET", "PUT"},
    f"{ADMIN_PREFIX}/users/{{user_id}}/quota": {"GET", "PUT", "DELETE"},
    f"{ADMIN_PREFIX}/users/{{user_id}}/background-pause": {"POST"},
    f"{ADMIN_PREFIX}/users/{{user_id}}/background-resume": {"POST"},
    f"{ADMIN_PREFIX}/capacity": {"GET"},
    f"{ADMIN_PREFIX}/upgrade-preview": {"GET"},
    f"{ADMIN_PREFIX}/deploy-status": {"GET"},
    f"{ADMIN_PREFIX}/rollback-readiness": {"GET"},
}

# The /api/v1/admin namespace additionally hosts unrelated route
# families (new304/37x/399) that declare the same prefix; their paths
# may exist in app.openapi() but are not part of this split.
SUBMODULE_OWNERSHIP: dict[str, set[str]] = {
    "invites": {
        "/invites",
        "/invites/{invite_id}",
        "/invite-schemes",
        "/invite-schemes/{scheme_id}",
        "/invite-schemes/{scheme_id}/generate-invites",
        "/invite-funnel",
        "/pool",
        "/capacity",
    },
    "users": {
        "/step-up",
        "/users",
        "/users/{user_id}/pause",
        "/users/{user_id}/resume",
        "/users/{user_id}/role",
        "/users/{user_id}/revoke-sessions",
        "/users/{user_id}/reset-password",
        "/users/{user_id}/quota",
        "/users/{user_id}/background-pause",
        "/users/{user_id}/background-resume",
    },
    "audit": {"/audit"},
    "ops": {
        "/system",
        "/registration-policy",
        "/upgrade-preview",
        "/deploy-status",
        "/rollback-readiness",
    },
}


def _openapi_admin_methods() -> dict[str, set[str]]:
    """path → upper-cased methods for the historical admin surface,
    read from the app's own OpenAPI document."""
    paths = app.openapi().get("paths", {})
    surface: dict[str, set[str]] = {}
    for path, operations in paths.items():
        if path not in HISTORICAL_ADMIN_SURFACE:
            continue
        surface[path] = {method.upper() for method in operations}
    return surface


def test_openapi_serves_exactly_the_historical_admin_surface():
    served = _openapi_admin_methods()
    missing = {p: m for p, m in HISTORICAL_ADMIN_SURFACE.items() if p not in served}
    assert not missing, f"admin paths lost by the split: {sorted(missing)}"
    drifted = {p: (served[p], m) for p, m in HISTORICAL_ADMIN_SURFACE.items() if served[p] != m}
    assert not drifted, f"admin methods drifted: {drifted}"
    assert len(served) == len(HISTORICAL_ADMIN_SURFACE)


def test_submodules_exist_and_own_disjoint_slices():
    package = importlib.import_module("lumirss.routers.admin")
    owned: set[str] = set()
    for name, expected_local in SUBMODULE_OWNERSHIP.items():
        module = importlib.import_module(f"lumirss.routers.admin.{name}")
        actual = {
            route.path
            for route in module.router.routes
            if isinstance(route, APIRoute)
        }
        assert actual == expected_local, f"{name} owns a different slice"
        assert not (actual & owned), f"{name} overlaps a sibling slice"
        owned |= actual
        assert hasattr(package, name)
    assert owned == {
        path.removeprefix(ADMIN_PREFIX) for path in HISTORICAL_ADMIN_SURFACE
    }


def test_shared_guard_names_remain_importable_from_the_package():
    # new3xx route modules and tests import these from
    # lumirss.routers.admin — the split must not break them.
    from lumirss.routers.admin import (  # noqa: F401
        _NO_STORE,
        _accounts,
        _forbid,
        _iso,
        _parse_iso_epoch,
        _probe_freshness,
        _require_admin,
        _require_owner,
    )


def test_endpoint_function_names_unchanged_for_operationid_stability():
    """operationId = route name (function __name__) + path + method."""
    expected_names = {
        "admin_step_up",
        "list_users",
        "create_invite",
        "generate_invites_from_scheme",
        "list_invites",
        "revoke_invite",
        "list_invite_schemes",
        "create_invite_scheme",
        "delete_invite_scheme",
        "invite_funnel",
        "pause_user",
        "resume_user",
        "set_user_role",
        "revoke_user_sessions",
        "reset_user_password",
        "pool_status",
        "pool_add",
        "audit_tail",
        "system_status",
        "get_registration_policy",
        "set_registration_policy",
        "get_user_quota",
        "set_user_quota",
        "clear_user_quota",
        "background_pause_user",
        "background_resume_user",
        "admin_capacity",
        "admin_upgrade_preview",
        "admin_deploy_status",
        "admin_rollback_readiness",
    }
    names: set[str] = set()
    for name in SUBMODULE_OWNERSHIP:
        module = importlib.import_module(f"lumirss.routers.admin.{name}")
        for route in module.router.routes:
            if isinstance(route, APIRoute):
                names.add(route.name)
    assert names == expected_names
