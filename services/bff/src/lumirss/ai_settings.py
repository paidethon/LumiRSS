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
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict

from lumirss.storage import Database

PROVIDER_OPENAI_COMPATIBLE = "openai_compatible"

SUPPORTED_SUMMARY_LANGUAGES = ("zh-CN", "en")
# 0016: translation target uses the same language set as summaries.
SUPPORTED_TRANSLATION_LANGUAGES = SUPPORTED_SUMMARY_LANGUAGES

KEY_PROVIDER = "ai.provider"
KEY_BASE_URL = "ai.base_url"
KEY_MODEL = "ai.model"
KEY_SUMMARY_LANGUAGE = "ai.summary_language"
KEY_TRANSLATION_LANGUAGE = "ai.translation_language"

MAX_MODEL_LENGTH = 200

_ErrorSink = Callable[[str], str]


def _identity(value: str) -> str:
    return value


def _validate_provider(value: str) -> str:
    if value not in (PROVIDER_OPENAI_COMPATIBLE,):
        raise ValueError(f"unsupported provider '{value}'")
    return value


def _validate_base_url(value: str) -> str:
    """OpenAI-compatible endpoint base (e.g. https://api.openai.com/v1).

    Same structural rules as the operator-configured service URLs: absolute
    http(s), no credentials/query/fragment, host root only (path must be
    empty, ``/`` or a version path such as ``/v1``). Blank clears the value.
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


# The complete allow-list of Lumi server settings. Anything not
# declared here can never be persisted.
_SETTING_SPECS: dict[str, tuple[str, _ErrorSink]] = {
    KEY_PROVIDER: (PROVIDER_OPENAI_COMPATIBLE, _validate_provider),
    KEY_BASE_URL: ("", _validate_base_url),
    KEY_MODEL: ("", _validate_model),
    KEY_SUMMARY_LANGUAGE: ("zh-CN", _validate_summary_language),
    KEY_TRANSLATION_LANGUAGE: ("zh-CN", _validate_translation_language),
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


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
