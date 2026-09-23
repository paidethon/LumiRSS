"""Persistent Lumi server AI settings (0015 Gate 2).

Design constraints:

- lumi.sqlite stores NON-SECRET AI configuration only. The API key is a
  server-side secret from the environment (AI_API_KEY) and is never a
  Lumi setting — the browser only ever learns ``configured: true/false``.
- Key/value persistence is allow-listed: every persisted key is declared
  with a validator. There is deliberately NO arbitrary JSON/env editor.
- Defaults live in code; the DB only stores user overrides. Loading is
  therefore always safe even on a fresh database.
"""

import urllib.parse
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from lumirss.storage import Database
from lumirss.util import utc_now as _utc_now

PROVIDER_OPENAI_COMPATIBLE = "openai_compatible"
PROVIDER_GEMINI = "gemini"

# The official Google Generative Language endpoint. Gemini profiles do
# NOT take a user-supplied base URL — this constant is the only endpoint
# a ``gemini`` profile can target (the BFF dials it with the profile's
# write-only API key).
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# Provider allow-list for NAMED PROFILES (P17). The GLOBAL default
# resolution stays OpenAI-compatible only (see _validate_provider).
PROFILE_PROVIDERS = (PROVIDER_OPENAI_COMPATIBLE, PROVIDER_GEMINI)

SUPPORTED_SUMMARY_LANGUAGES = ("zh-CN", "en")
# 0016: translation target uses the same language set as summaries.
SUPPORTED_TRANSLATION_LANGUAGES = SUPPORTED_SUMMARY_LANGUAGES

KEY_PROVIDER = "ai.provider"
KEY_BASE_URL = "ai.base_url"
KEY_MODEL = "ai.model"
KEY_SUMMARY_LANGUAGE = "ai.summary_language"
KEY_TRANSLATION_LANGUAGE = "ai.translation_language"

# Gate: which engine renders translations. "ai" = OpenAI-compatible
# provider (cloud or self-hosted); "libretranslate" = self-hosted MT
# service reached THROUGH the BFF; "browser" = the browser's own
# Translator API (this device; the BFF is never called for it).
TRANSLATION_ENGINE_AI = "ai"
TRANSLATION_ENGINE_LIBRETRANSLATE = "libretranslate"
TRANSLATION_ENGINE_BROWSER = "browser"
SUPPORTED_TRANSLATION_ENGINES = (
    TRANSLATION_ENGINE_AI,
    TRANSLATION_ENGINE_LIBRETRANSLATE,
    TRANSLATION_ENGINE_BROWSER,
)
KEY_TRANSLATION_ENGINE = "translation.engine"
KEY_LIBRETRANSLATE_URL = "translation.libretranslate_url"

# F064：AI 配额（可空 = 不限）。window: "" | day | month；max_calls: 0..10000
# （0 = 不限）。服务端本地时区窗口计数，见 ai_quota.py。
KEY_QUOTA_WINDOW = "ai.quota_window"
KEY_QUOTA_MAX_CALLS = "ai.quota_max_calls"
SUPPORTED_QUOTA_WINDOWS = ("", "day", "month")
MAX_QUOTA_CALLS = 10000

MAX_MODEL_LENGTH = 200

_ErrorSink = Callable[[str], str]


def _identity(value: str) -> str:
    return value


def _validate_provider(value: str) -> str:
    if value not in (PROVIDER_OPENAI_COMPATIBLE,):
        raise ValueError(f"unsupported provider '{value}'")
    return value


def _validate_profile_provider(value: str) -> str:
    """Provider type of one NAMED profile (P17): OpenAI-compatible or
    the native Google Gemini REST API."""
    if value not in PROFILE_PROVIDERS:
        raise ValueError(f"provider must be one of {', '.join(PROFILE_PROVIDERS)}")
    return value


def _validate_base_url(value: str) -> str:
    """OpenAI-compatible endpoint base (e.g. https://api.openai.com/v1).

    Same structural rules as the operator-configured service URLs: absolute
    http(s), no credentials/query/fragment, host root only (path must be
    empty, ``/`` or a version path such as ``/v1``). Blank clears the value.

    SSRF baseline (quality closure): https is required unless the hostname
    is on the operator's private-host allow-list — the BFF dials these
    URLs server-side and sends the AI API key as a bearer token, so an
    arbitrary http://10.x base must not be storable.
    """
    clean = value.strip()
    if not clean:
        return ""
    parts = urllib.parse.urlsplit(clean)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("must be an absolute http(s) URL")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("must not carry credentials, a query or a fragment")
    if parts.path != "" and not parts.path.startswith("/"):
        raise ValueError("must not carry a non-root path")
    if parts.scheme != "https":
        from lumirss.feed_preview import hostname_allowlisted

        if not hostname_allowlisted(parts.hostname):
            raise ValueError(
                "must use https unless the host is on the private-host allow-list"
            )
    return clean.rstrip("/")


def _validate_model(value: str) -> str:
    clean = value.strip()
    if len(clean) > MAX_MODEL_LENGTH:
        raise ValueError(f"model must be at most {MAX_MODEL_LENGTH} characters")
    if any(ord(char) < 32 for char in clean):
        raise ValueError("model must not contain control characters")
    return clean


def _validate_summary_language(value: str) -> str:
    if value not in SUPPORTED_SUMMARY_LANGUAGES:
        raise ValueError(
            f"summary language must be one of {', '.join(SUPPORTED_SUMMARY_LANGUAGES)}"
        )
    return value


def _validate_translation_language(value: str) -> str:
    if value not in SUPPORTED_TRANSLATION_LANGUAGES:
        raise ValueError(
            f"translation language must be one of {', '.join(SUPPORTED_TRANSLATION_LANGUAGES)}"
        )
    return value


def _validate_quota_window(value: str) -> str:
    if value not in SUPPORTED_QUOTA_WINDOWS:
        raise ValueError("quota window must be one of: (empty), day, month")
    return value


def _validate_quota_max_calls(value: int | str) -> str:
    text = str(value).strip()
    if not text.isdigit() or int(text) > MAX_QUOTA_CALLS:
        raise ValueError(
            f"quota max calls must be an integer 0..{MAX_QUOTA_CALLS} (0 = unlimited)"
        )
    return str(int(text))


def _validate_translation_engine(value: str) -> str:
    if value not in SUPPORTED_TRANSLATION_ENGINES:
        raise ValueError(
            f"translation engine must be one of {', '.join(SUPPORTED_TRANSLATION_ENGINES)}"
        )
    return value


# SecretsStore key NAME (not a credential) for the optional LibreTranslate
# API key — write-only, same join convention as WEBDAV_SECRET_KEY.
LIBRETRANSLATE_KEY_NAME = ".".join(("translation", "libretranslate-key"))


# The complete allow-list of Lumi server settings. Anything not
# declared here can never be persisted.
_SETTING_SPECS: dict[str, tuple[str, _ErrorSink]] = {
    KEY_PROVIDER: (PROVIDER_OPENAI_COMPATIBLE, _validate_provider),
    KEY_BASE_URL: ("", _validate_base_url),
    KEY_MODEL: ("", _validate_model),
    KEY_SUMMARY_LANGUAGE: ("zh-CN", _validate_summary_language),
    KEY_TRANSLATION_LANGUAGE: ("zh-CN", _validate_translation_language),
    KEY_TRANSLATION_ENGINE: (TRANSLATION_ENGINE_AI, _validate_translation_engine),
    KEY_LIBRETRANSLATE_URL: ("", _validate_base_url),
    KEY_QUOTA_WINDOW: ("", _validate_quota_window),
    KEY_QUOTA_MAX_CALLS: ("0", _validate_quota_max_calls),
}


class InvalidAiSettings(Exception):
    """A settings value failed allow-list validation (message is browser-safe)."""


class AiSettingsUpdate(BaseModel):
    """PUT /api/v1/settings/ai body — every field optional, validated.

    Missing fields keep their current value; blank baseUrl/model clear it.
    There is no secret field on this model by design, and unknown fields
    are rejected (extra="forbid") so an attempt to smuggle e.g. an apiKey
    into the settings store fails loudly instead of being ignored.
    """

    model_config = ConfigDict(extra="forbid")

    provider: Literal["openai_compatible"] | None = None
    baseUrl: str | None = None
    model: str | None = None
    summaryLanguage: Literal["zh-CN", "en"] | None = None
    translationLanguage: Literal["zh-CN", "en"] | None = None
    translationEngine: Literal["ai", "libretranslate", "browser"] | None = None
    libretranslateUrl: str | None = None
    # F064：用量限制（window: ""=不限/day/month；maxCalls: 0=不限,1..10000）。
    quotaWindow: Literal["", "day", "month"] | None = None
    quotaMaxCalls: int | None = Field(default=None, ge=0, le=MAX_QUOTA_CALLS)




class AiSettingsStore:
    """Typed access to the 0015 AI settings over the allow-listed KV store."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def load(self) -> dict[str, str]:
        """All allow-listed values (defaults for keys never written)."""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT key, value FROM lumi_settings"
        )
        stored = {row["key"]: row["value"] for row in rows}
        return {
            key: stored.get(key, spec[0])
            for key, spec in _SETTING_SPECS.items()
        }

    async def save(self, update: AiSettingsUpdate) -> dict[str, str]:
        """Validate + persist only the provided (non-None) fields."""
        await self._db.migrate()
        current = await self.load()
        next_values = dict(current)
        for field, key in (
            ("provider", KEY_PROVIDER),
            ("baseUrl", KEY_BASE_URL),
            ("model", KEY_MODEL),
            ("summaryLanguage", KEY_SUMMARY_LANGUAGE),
            ("translationLanguage", KEY_TRANSLATION_LANGUAGE),
            ("translationEngine", KEY_TRANSLATION_ENGINE),
            ("libretranslateUrl", KEY_LIBRETRANSLATE_URL),
            ("quotaWindow", KEY_QUOTA_WINDOW),
            ("quotaMaxCalls", KEY_QUOTA_MAX_CALLS),
        ):
            value = getattr(update, field)
            if value is None:
                continue
            try:
                next_values[key] = _SETTING_SPECS[key][1](value)
            except ValueError as exc:
                raise InvalidAiSettings(
                    f"Invalid {key}: {exc}"
                ) from exc
        for key, value in next_values.items():
            if value != current.get(key):
                await self._db.execute(
                    "INSERT INTO lumi_settings (key, value, updated_at) "
                    "VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                    "updated_at = excluded.updated_at",
                    (key, value, _utc_now()),
                )
        return next_values
