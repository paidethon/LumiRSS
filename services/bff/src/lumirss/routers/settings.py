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
    SettingsHistoryEntry,
    SettingsHistoryList,
    SettingsRevertResult,
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
    before_doc, _ = await store.load()
    try:
        merged = await store.save(update)
    except ValueError as exc:
        raise InvalidAppSettings(str(exc)) from exc
    # F33：记录实际变化的键（不含任何密钥——portable 设置无密钥字段）
    from lumirss.settings_history import SettingsHistoryStore, compute_diff

    diff = compute_diff(before_doc.model_dump(), merged.model_dump())
    await SettingsHistoryStore(request.app.state.db).record("update", diff)
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

@router.get("/api/v1/settings/history", response_model=SettingsHistoryList)
async def get_settings_history(request: Request, limit: int = 10) -> SettingsHistoryList:
    """F33：最近的设置变更（新→旧；只含 portable 设置，无密钥）。"""
    from lumirss.settings_history import SettingsHistoryStore

    items = await SettingsHistoryStore(request.app.state.db).list_history(limit)
    return SettingsHistoryList(
        items=[SettingsHistoryEntry(**item) for item in items]
    )


@router.post("/api/v1/settings/history/{history_id}/revert", response_model=SettingsRevertResult)
async def revert_settings_history(
    history_id: int, request: Request
) -> SettingsRevertResult:
    """F33：回退一次历史变更。

    冲突语义（回退不覆盖新修改）：对每个变更键，若当前值已不再等于
    该条记录的 after 值（之后又被改过），则跳过该键并如实返回；
    其余键应用 before 值。回退本身作为一次 update 记入历史（可再
    次撤销）；至少一个键被应用时才有实际写入。

    N184 显式化：冲突键不再只以 skipped 映射出现——响应带 restored
    （已回退键列表）与 conflicts（键 + 原因清单），由 UI 明示。"""
    from lumirss.app_settings import PortableSettingsPatch
    from lumirss.models import SettingsRevertConflict
    from lumirss.settings_history import SettingsHistoryStore, compute_diff

    store = _get_app_settings_store(request)
    entry = await SettingsHistoryStore(request.app.state.db).get_entry(history_id)
    if entry is None:
        from lumirss.app_settings import InvalidAppSettings

        raise InvalidAppSettings("history entry not found")
    current_doc, _ = await store.load()
    current = current_doc.model_dump()
    skipped: dict[str, object] = {}
    conflicts: list[SettingsRevertConflict] = []
    patch_values: dict[str, object] = {}
    for key, change in entry["diff"].items():
        if current.get(key) == change["after"]:
            patch_values[key] = change["before"]
        else:
            skipped[key] = current.get(key)
            conflicts.append(
                SettingsRevertConflict(
                    key=key,
                    reason="该键在记录之后又被修改，回退不覆盖新修改",
                )
            )
    if not patch_values:
        return SettingsRevertResult(
            applied={}, skipped=skipped, restored=[], conflicts=conflicts
        )
    try:
        patch = PortableSettingsPatch.model_validate(patch_values)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise InvalidAppSettings(
            f"Invalid {first.get('loc', ())}: {first.get('msg', 'value rejected')}"
        ) from exc
    merged = await store.save(patch)
    after_doc = merged.model_dump()
    diff = compute_diff(current, after_doc)
    await SettingsHistoryStore(request.app.state.db).record("revert", diff)
    return SettingsRevertResult(
        applied=patch_values,
        skipped=skipped,
        restored=sorted(patch_values),
        conflicts=conflicts,
    )
