"""Settings routes (moved verbatim from main.py)."""



from fastapi import APIRouter, Request, Response
from pydantic import ValidationError

from lumirss.app_settings import (
    AppSettingsConflict,
    InvalidAppSettings,
    PortableSettingsPatch,
)
from lumirss.deps import _get_app_settings_store
from lumirss.models import (
    AppSettingsView,
)

router = APIRouter()


def _reject_nonfinite(value: str) -> float:
    """Refuse NaN/Infinity/… JSON number tokens before pydantic sees them."""
    raise InvalidAppSettings(f"non-finite number '{value}' is not allowed")


def _parse_settings_patch(raw: bytes) -> tuple[PortableSettingsPatch, int | None]:
    """Strict body parsing: every invalid payload becomes a stable 400.

    0021: the body may carry ``baseRevision`` (int ≥ 0) — the revision the
    client last saw (optimistic concurrency). It is transport metadata,
    popped before settings validation so it can never masquerade as a
    settings key."""
    import json as _json

    try:
        parsed = _json.loads(raw, parse_constant=_reject_nonfinite)
    except (_json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidAppSettings("request body must be a valid JSON object") from exc
    if not isinstance(parsed, dict):
        raise InvalidAppSettings("request body must be a JSON object")
    base_revision_raw = parsed.pop("baseRevision", None)
    if base_revision_raw is None:
        base_revision = None
    elif isinstance(base_revision_raw, int) and not isinstance(
        base_revision_raw, bool
    ) and base_revision_raw >= 0:
        base_revision = base_revision_raw
    else:
        raise InvalidAppSettings("Invalid baseRevision: must be a non-negative int")
    try:
        patch = PortableSettingsPatch.model_validate(parsed)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ()))
        raise InvalidAppSettings(
            f"Invalid {location}: {first.get('msg', 'value rejected')}"
        ) from exc
    return patch, base_revision


def _app_settings_json(
    document, stored: bool, revision: int | None = None
) -> dict[str, object]:
    """Browser-safe portable settings view — no secrets exist by design."""
    payload = document.model_dump()
    view: dict[str, object] = {
        "schemaVersion": payload["schemaVersion"],
        "stored": stored,
        **payload,
    }
    if revision is not None:
        view["revision"] = revision
    return view


@router.get("/api/v1/settings", response_model=AppSettingsView)
async def get_app_settings(request: Request) -> dict[str, object]:
    """Current portable settings (defaults when nothing was ever stored).

    ``stored`` reports whether the server holds an explicit document — the
    client seeds it from its local values on first visit (migration) and
    treats it as authoritative afterwards. GET never mutates anything.
    """
    store = _get_app_settings_store(request)
    document, stored = await store.load()
    return _app_settings_json(document, stored, await store.document_revision())


@router.patch("/api/v1/settings", response_model=AppSettingsView)
async def patch_app_settings(request: Request) -> dict[str, object]:
    """Persist a partial portable settings update (strictly validated).

    The body is parsed manually so that EVERY invalid payload — unknown
    key, wrong type, out-of-range, NaN/Infinity, malformed JSON — is
    rejected with the stable 400 invalid_app_settings error (FastAPI's
    default 422 serialization crashes on non-finite numbers). There is
    deliberately no field that can carry any secret.

    0021 multi-device semantics: a body carrying ``baseRevision`` that no
    longer matches the stored document is refused with the stable 409
    app_settings_conflict — the stale client re-hydrates and retries.
    Bodies without baseRevision keep the historical last-write-wins
    behavior (older clients unaffected).
    """
    update, base_revision = _parse_settings_patch(await request.body())
    store = _get_app_settings_store(request)
    if base_revision is not None:
        current_revision = await store.document_revision()
        if current_revision != base_revision:
            raise AppSettingsConflict(
                "Settings were changed by another device; reload and retry."
            )
    try:
        merged = await store.save(update)
    except ValueError as exc:
        raise InvalidAppSettings(str(exc)) from exc
    return _app_settings_json(merged, True, await store.document_revision())


@router.delete("/api/v1/settings", status_code=204)
async def delete_app_settings(request: Request) -> Response:
    """Reset portable settings to defaults (removes the stored document).

    The next GET reports stored=false again; the client may re-seed from
    its local values afterwards.
    """
    store = _get_app_settings_store(request)
    await store.reset()
    return Response(status_code=204)


