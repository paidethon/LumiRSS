"""Ai_settings routes (moved verbatim from main.py)."""


from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, field_validator

from lumirss.ai_profiles import (
    PURPOSES,
    AiProfileStore,
)
from lumirss.ai_settings import (
    KEY_BASE_URL,
    KEY_LIBRETRANSLATE_URL,
    KEY_MODEL,
    KEY_PROVIDER,
    KEY_SUMMARY_LANGUAGE,
    KEY_TRANSLATION_ENGINE,
    KEY_TRANSLATION_LANGUAGE,
    AiSettingsUpdate,
)
from lumirss.ai_translation_segments import (
    LIBRETRANSLATE_KEY_NAME,
)
from lumirss.config import LumiSettings
from lumirss.deps import (
    _get_ai_profile_store,
    _get_ai_settings_store,
    _get_secrets_store,
)
from lumirss.models import (
    AiProfile,
    AiSettingsView,
)
from lumirss.rsshub_control import (
    MAX_SECRET_LENGTH,
)
from lumirss.secrets_store import SecretsStore

router = APIRouter()


async def _ai_settings_json(
    values: dict[str, str],
    profiles: AiProfileStore | None = None,
    secrets: SecretsStore | None = None,
) -> dict[str, object]:
    """Browser-safe AI settings view — NEVER contains an API key.

    Extends the 0015 shape with the browser-managed profile layer:
    ``purposes`` (purpose → profile id or "default") and
    ``purposeStatus`` (effective, secret-free resolution per purpose).
    """
    settings = LumiSettings()
    env_key = settings.AI_API_KEY.get_secret_value()
    secrets = secrets or SecretsStore(settings.secrets_path)
    payload: dict[str, object] = {
        "provider": values[KEY_PROVIDER],
        "baseUrl": values[KEY_BASE_URL],
        "model": values[KEY_MODEL],
        "summaryLanguage": values[KEY_SUMMARY_LANGUAGE],
        "translationLanguage": values[KEY_TRANSLATION_LANGUAGE],
        "translationEngine": values[KEY_TRANSLATION_ENGINE],
        "libretranslateUrl": values[KEY_LIBRETRANSLATE_URL],
        "libretranslateKeyConfigured": bool(
            (secrets.get(LIBRETRANSLATE_KEY_NAME) or "").strip()
        ),
        "configured": settings.ai_configured,
        "envKeyConfigured": bool(env_key.strip()),
        "defaultKeyConfigured": settings.ai_configured
        or (profiles is not None and profiles.default_key_configured()),
    }
    if profiles is not None:
        payload["purposes"] = await profiles.load_purposes()
        status: dict[str, object] = {}
        for purpose in PURPOSES:
            effective = await profiles.effective_config(purpose, values, env_key)
            status[purpose] = {
                "profileId": effective.profile_id or "default",
                "source": effective.source,
                "profileLabel": effective.profile_label,
                "baseUrl": effective.base_url,
                "model": effective.model,
                "keyConfigured": effective.api_key is not None,
                "keySource": effective.key_source,
                "configured": effective.configured,
            }
        payload["purposeStatus"] = status
    return payload


@router.get(
    "/api/v1/settings/ai",
    response_model=AiSettingsView,
    response_model_exclude_none=False,  # unmapped purpose → profileLabel null
)
async def get_ai_settings(request: Request) -> dict[str, object]:
    """Current AI settings + purpose resolution.

    No response field ever contains an API key: ``configured`` /
    ``envKeyConfigured`` / ``defaultKeyConfigured`` /
    ``purposeStatus.*.keyConfigured`` are booleans only.
    """
    store = _get_ai_settings_store(request)
    profiles = _get_ai_profile_store(request)
    return await _ai_settings_json(
        await store.load(), profiles, _get_secrets_store(request)
    )


@router.put(
    "/api/v1/settings/ai",
    response_model=AiSettingsView,
    response_model_exclude_none=False,
)
async def put_ai_settings(
    update: AiSettingsUpdate, request: Request
) -> dict[str, object]:
    """Persist non-secret GLOBAL (default) AI settings.

    There is deliberately no API-key field here: keys live in the
    SecretsStore via the dedicated write-only key endpoints.
    """
    store = _get_ai_settings_store(request)
    profiles = _get_ai_profile_store(request)
    return await _ai_settings_json(
        await store.save(update), profiles, _get_secrets_store(request)
    )


class SecretValuePut(BaseModel):
    """Write-only secret body (shared by AI keys and RSSHub secrets).

    0021 hardening: bounded length (same bound as the RSSHub secret
    schema) and control-character rejection at INPUT time — a control
    character in an API key is never legitimate, and storing one would
    poison env-file rendering / upstream calls until the value is
    replaced.
    """

    value: str = Field(min_length=1, max_length=MAX_SECRET_LENGTH)

    @field_validator("value")
    @classmethod
    def _reject_control_characters(cls, value: str) -> str:
        if any(ord(char) < 32 for char in value):
            raise ValueError("value must not contain control characters.")
        return value


class AiProfileCreate(BaseModel):
    """POST /api/v1/settings/ai/profiles body (metadata only, no key)."""

    label: str = Field(min_length=1)
    baseUrl: str = ""
    model: str = ""
    enabled: bool = True


class AiProfileUpdate(BaseModel):
    """PATCH /api/v1/settings/ai/profiles/{id} body (all optional)."""

    label: str | None = None
    baseUrl: str | None = None
    model: str | None = None
    enabled: bool | None = None


class AiPurposesUpdate(BaseModel):
    """PUT /api/v1/settings/ai/purposes body (each purpose optional).

    Every target is either the built-in ``default`` resolution or an
    existing profile id.
    """

    summary: str | None = None
    translation: str | None = None
    chat: str | None = None


@router.put("/api/v1/settings/ai/key", status_code=204)
async def put_default_ai_key(secret: SecretValuePut, request: Request) -> Response:
    """Store the default (legacy) AI API key from the browser.

    Write-only: the value is persisted server-side in the SecretsStore
    and can never be read back over the API. The env ``AI_API_KEY``
    remains as fallback when no browser key is set.
    """
    _get_ai_profile_store(request).set_default_key(secret.value.strip())
    return Response(status_code=204)


@router.delete("/api/v1/settings/ai/key", status_code=204)
async def delete_default_ai_key(request: Request) -> Response:
    """Remove the browser-set default key (env fallback resumes)."""
    _get_ai_profile_store(request).clear_default_key()
    return Response(status_code=204)


@router.put("/api/v1/settings/translation/libretranslate-key", status_code=204)
async def put_libretranslate_key(secret: SecretValuePut, request: Request) -> Response:
    """Write-only LibreTranslate API key (optional; empty string clears)."""
    value = secret.value.strip()
    if not value:
        _get_secrets_store(request).delete(LIBRETRANSLATE_KEY_NAME)
    else:
        _get_secrets_store(request).set(LIBRETRANSLATE_KEY_NAME, value)
    return Response(status_code=204)


@router.delete("/api/v1/settings/translation/libretranslate-key", status_code=204)
async def delete_libretranslate_key(request: Request) -> Response:
    """Remove the optional LibreTranslate API key."""
    _get_secrets_store(request).delete(LIBRETRANSLATE_KEY_NAME)
    return Response(status_code=204)


class LibreTranslateTestResult(BaseModel):
    """POST /api/v1/settings/translation/libretranslate-test."""

    status: Literal["ok", "failed"]
    message: str | None = None


@router.post(
    "/api/v1/settings/translation/libretranslate-test",
    response_model=LibreTranslateTestResult,
)
async def test_libretranslate(request: Request) -> dict[str, object]:
    """Probe the configured LibreTranslate server (GET /languages)."""
    values = await _get_ai_settings_store(request).load()
    base = values[KEY_LIBRETRANSLATE_URL]
    if not base:
        return {"status": "failed", "message": "LibreTranslate 服务地址未配置。"}
    try:
        response = await request.app.state.http_client.get(
            f"{base}/languages", timeout=10.0
        )
        response.raise_for_status()
        languages = response.json()
        if not isinstance(languages, list):
            raise ValueError("unexpected payload")
        return {"status": "ok", "message": f"连接成功（{len(languages)} 种语言）。"}
    except Exception:
        return {"status": "failed", "message": "连接失败：BFF 无法访问该地址或服务未就绪。"}


@router.get("/api/v1/settings/ai/profiles", response_model=list[AiProfile])
async def get_ai_profiles(request: Request) -> list[dict[str, object]]:
    """All AI profiles (metadata + ``keyConfigured`` flag, never keys)."""
    return await _get_ai_profile_store(request).list_profiles()


@router.post(
    "/api/v1/settings/ai/profiles",
    status_code=201,
    response_model=AiProfile,
)
async def create_ai_profile(
    body: AiProfileCreate, request: Request
) -> dict[str, object]:
    """Create a profile. The API key is set separately (write-only)."""
    return await _get_ai_profile_store(request).create_profile(
        label=body.label,
        base_url=body.baseUrl,
        model=body.model,
        enabled=body.enabled,
    )


@router.patch(
    "/api/v1/settings/ai/profiles/{profile_id}",
    response_model=AiProfile,
)
async def patch_ai_profile(
    profile_id: str, body: AiProfileUpdate, request: Request
) -> dict[str, object]:
    """Update profile metadata (label / baseUrl / model / enabled)."""
    return await _get_ai_profile_store(request).update_profile(
        profile_id,
        label=body.label,
        base_url=body.baseUrl,
        model=body.model,
        enabled=body.enabled,
    )


@router.delete("/api/v1/settings/ai/profiles/{profile_id}", status_code=204)
async def delete_ai_profile(
    profile_id: str, request: Request
) -> Response:
    """Delete a profile, its secret, and any purpose mapping to it."""
    await _get_ai_profile_store(request).delete_profile(profile_id)
    return Response(status_code=204)


@router.put("/api/v1/settings/ai/profiles/{profile_id}/secret", status_code=204)
async def put_ai_profile_secret(
    profile_id: str, secret: SecretValuePut, request: Request
) -> Response:
    """Set/replace one profile's API key (write-only, never echoed)."""
    profiles = _get_ai_profile_store(request)
    await profiles.get_profile(profile_id)  # 404 when unknown
    profiles.set_profile_key(profile_id, secret.value.strip())
    return Response(status_code=204)


@router.delete("/api/v1/settings/ai/profiles/{profile_id}/secret", status_code=204)
async def delete_ai_profile_secret(
    profile_id: str, request: Request
) -> Response:
    """Revoke one profile's API key."""
    profiles = _get_ai_profile_store(request)
    await profiles.get_profile(profile_id)  # 404 when unknown
    profiles.clear_profile_key(profile_id)
    return Response(status_code=204)


@router.get("/api/v1/settings/ai/purposes", response_model=dict[str, str])
async def get_ai_purposes(request: Request) -> dict[str, str]:
    """Purpose → profile id (or ``default``) mapping."""
    return await _get_ai_profile_store(request).load_purposes()


@router.put("/api/v1/settings/ai/purposes", response_model=dict[str, str])
async def put_ai_purposes(
    body: AiPurposesUpdate, request: Request
) -> dict[str, str]:
    """Assign profiles to purposes. ``default`` selects the global
    settings + default key resolution."""
    provided = {
        purpose: value
        for purpose, value in (
            ("summary", body.summary),
            ("translation", body.translation),
            ("chat", body.chat),
        )
        if value is not None
    }
    return await _get_ai_profile_store(request).save_purposes(provided)


