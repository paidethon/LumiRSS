"""Browser-managed AI profiles + purpose mapping.

Extends the 0015 single-server-key model: the user may now define any
number of NAMED profiles ("GLM 摘要", "DeepSeek 翻译", …) entirely from
the browser, each with its own OpenAI-compatible base URL / model and its
own API key, and map the three AI purposes (summary / translation /
article conversation) onto them independently.

Security model (unchanged invariants, one new storage namespace):

- API keys are server-side secrets in the SecretsStore (chmod-600 JSON
  outside lumi.sqlite, excluded from backups by construction). Keys are
  WRITE-ONLY over the API: no endpoint ever echoes one.
- lumi.sqlite stores profile METADATA only (label, base URL, model,
  enabled) — never a key.
- The legacy configuration stays usable: the built-in ``default``
  resolution uses the global AI settings (base URL / model) and its key
  comes from the SecretsStore (``ai.api_key``) or, as before, the
  ``AI_API_KEY`` environment variable as fallback.
"""

import json
import uuid
from dataclasses import dataclass
from typing import Literal

from lumirss.ai_settings import (
    AiSettingsStore,
    InvalidAiSettings,
    KEY_BASE_URL,
    KEY_MODEL,
    KEY_PROVIDER,
    _validate_base_url,
    _validate_model,
)
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database

PURPOSES = ("summary", "translation", "chat")
Purpose = Literal["summary", "translation", "chat"]

DEFAULT_PROFILE_ID = "default"
PROFILES_KV_KEY = "ai.purposes"

MAX_LABEL_LENGTH = 80

_PROFILE_SECRET_PREFIX = "ai.profile."


def profile_secret_key(profile_id: str) -> str:
    """SecretsStore key holding one profile's API key."""
    return f"{_PROFILE_SECRET_PREFIX}{profile_id}.api_key"


def default_secret_key() -> str:
    """SecretsStore key holding the default (legacy) AI API key."""
    return "ai.api_key"


class AiProfileNotFound(Exception):
    """No profile with the given id (message is browser-safe)."""


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_label(value: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError("label must not be blank")
    if len(clean) > MAX_LABEL_LENGTH:
        raise ValueError(f"label must be at most {MAX_LABEL_LENGTH} characters")
    if any(ord(char) < 32 for char in clean):
        raise ValueError("label must not contain control characters")
    return clean


@dataclass(frozen=True)
class EffectiveAiConfig:
    """Resolved runtime configuration for one purpose (server-side only).

    ``api_key`` is the resolved secret (or None when nothing is
    configured); it must never be serialized into any API response.
    """

    source: str  # "default" | "profile"
    profile_id: str | None
    profile_label: str | None
    base_url: str
    model: str
    provider: str
    api_key: str | None
    key_source: str  # "profile_secret" | "default_secret" | "env" | "missing"

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model and self.api_key)


class PurposeAiSettings:
    """``AiSettingsStore``-compatible read view for one purpose.

    Lets the 0015/0016 services stay unchanged: ``load()`` returns the
    global settings with base URL / model replaced by the mapped
    profile's when an enabled profile is mapped to this purpose — so
    cache identities and provider calls automatically use the profile.
    Writes still target the GLOBAL settings (profiles have their own
    API); the services never call ``save`` anyway.
    """

    def __init__(
        self,
        base: AiSettingsStore,
        profiles: "AiProfileStore",
        purpose: str,
    ) -> None:
        self._base = base
        self._profiles = profiles
        self._purpose = purpose

    async def load(self) -> dict[str, str]:
        values = await self._base.load()
        effective = await self._profiles.effective_config(
            self._purpose, values, env_api_key=""
        )
        if effective.source == "profile":
            return {
                **values,
                KEY_BASE_URL: effective.base_url,
                KEY_MODEL: effective.model,
            }
        return values

    async def save(self, update) -> dict[str, str]:
        return await self._base.save(update)


class AiProfileStore:
    """Profiles + purpose mapping over lumi.sqlite and the SecretsStore."""

    def __init__(self, db: Database, secrets: SecretsStore) -> None:
        self._db = db
        self._secrets = secrets

    # -- metadata -----------------------------------------------------

    async def _migrate(self) -> None:
        await self._db.migrate()

    async def list_profiles(self) -> list[dict[str, object]]:
        await self._migrate()
        rows = await self._db.fetch_all(
            "SELECT id, label, provider, base_url, model, enabled, created_at, updated_at FROM ai_profiles ORDER BY created_at, id"
        )
        flags = self._secrets.configured_map(
            [profile_secret_key(row["id"]) for row in rows]
        )
        return [
            {
                "id": row["id"],
                "label": row["label"],
                "provider": row["provider"],
                "baseUrl": row["base_url"],
                "model": row["model"],
                "enabled": bool(row["enabled"]),
                "keyConfigured": flags.get(profile_secret_key(row["id"]), False),
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
            }
            for row in rows
        ]

    async def _fetch_row(self, profile_id: str):
        return await self._db.fetch_one(
            "SELECT id, label, provider, base_url, model, enabled, created_at, updated_at FROM ai_profiles WHERE id = ?",
            (profile_id,),
        )

    async def create_profile(
        self,
        *,
        label: str,
        base_url: str = "",
        model: str = "",
        enabled: bool = True,
    ) -> dict[str, object]:
        await self._migrate()
        values = self._validate_fields(label=label, base_url=base_url, model=model)
        profile_id = uuid.uuid4().hex[:20]
        now = _utc_now()
        await self._db.execute(
            "INSERT INTO ai_profiles (id, label, provider, base_url, model, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                profile_id,
                values["label"],
                values["provider"],
                values["base_url"],
                values["model"],
                1 if enabled else 0,
                now,
                now,
            ),
        )
        return await self.get_profile(profile_id)

    async def update_profile(
        self,
        profile_id: str,
        *,
        label: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        enabled: bool | None = None,
    ) -> dict[str, object]:
        await self._migrate()
        row = await self._fetch_row(profile_id)
        if row is None:
            raise AiProfileNotFound("AI profile not found.")
        values = self._validate_fields(
            label=label if label is not None else row["label"],
            base_url=base_url if base_url is not None else row["base_url"],
            model=model if model is not None else row["model"],
        )
        await self._db.execute(
            "UPDATE ai_profiles SET label = ?, base_url = ?, model = ?, enabled = ?, updated_at = ? WHERE id = ?",
            (
                values["label"],
                values["base_url"],
                values["model"],
                (1 if enabled else 0) if enabled is not None else row["enabled"],
                _utc_now(),
                profile_id,
            ),
        )
        return await self.get_profile(profile_id)

    async def get_profile(self, profile_id: str) -> dict[str, object]:
        await self._migrate()
        row = await self._fetch_row(profile_id)
        if row is None:
            raise AiProfileNotFound("AI profile not found.")
        return {
            "id": row["id"],
            "label": row["label"],
            "provider": row["provider"],
            "baseUrl": row["base_url"],
            "model": row["model"],
            "enabled": bool(row["enabled"]),
            "keyConfigured": self._secrets.configured(
                profile_secret_key(profile_id)
            ),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    async def delete_profile(self, profile_id: str) -> None:
        """Remove a profile, its secret, and any purpose mapping to it."""
        await self._migrate()
        row = await self._fetch_row(profile_id)
        if row is None:
            raise AiProfileNotFound("AI profile not found.")
        await self._db.execute(
            "DELETE FROM ai_profiles WHERE id = ?", (profile_id,)
        )
        self._secrets.delete(profile_secret_key(profile_id))
        purposes = await self.load_purposes()
        changed = False
        for purpose in PURPOSES:
            if purposes[purpose] == profile_id:
                purposes[purpose] = DEFAULT_PROFILE_ID
                changed = True
        if changed:
            await self.save_purposes(purposes)

    # -- secrets (write-only over the API) ----------------------------

    def set_profile_key(self, profile_id: str, value: str) -> None:
        self._secrets.set(profile_secret_key(profile_id), value)

    def clear_profile_key(self, profile_id: str) -> bool:
        return self._secrets.delete(profile_secret_key(profile_id))

    def set_default_key(self, value: str) -> None:
        self._secrets.set(default_secret_key(), value)

    def clear_default_key(self) -> bool:
        return self._secrets.delete(default_secret_key())

    def default_key_configured(self) -> bool:
        """Whether a browser-set default key exists in the SecretsStore."""
        return self._secrets.configured(default_secret_key())

    # -- purpose mapping ----------------------------------------------

    async def load_purposes(self) -> dict[str, str]:
        """Purpose → profile id map (defaults when never saved)."""
        await self._migrate()
        row = await self._db.fetch_one(
            "SELECT value FROM lumi_settings WHERE key = ?", (PROFILES_KV_KEY,)
        )
        purposes: dict[str, str] = {
            purpose: DEFAULT_PROFILE_ID for purpose in PURPOSES
        }
        if row is not None:
            try:
                parsed = json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                parsed = None
            if isinstance(parsed, dict):
                for purpose in PURPOSES:
                    value = parsed.get(purpose)
                    if isinstance(value, str) and value:
                        purposes[purpose] = value
        return purposes

    async def save_purposes(self, purposes: dict[str, str]) -> dict[str, str]:
        """Validate + persist the purpose map; returns the saved map."""
        unknown = set(purposes) - set(PURPOSES)
        if unknown:
            raise InvalidAiSettings(
                f"unknown AI purpose: {', '.join(sorted(unknown))}"
            )
        current = await self.load_purposes()
        for purpose, target in purposes.items():
            if target != DEFAULT_PROFILE_ID:
                row = await self._fetch_row(target)
                if row is None:
                    raise AiProfileNotFound(
                        f"AI profile not found for purpose '{purpose}'."
                    )
            current[purpose] = target
        await self._db.execute(
            "INSERT INTO lumi_settings (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (PROFILES_KV_KEY, json.dumps(current, ensure_ascii=False), _utc_now()),
        )
        return current

    # -- resolution -----------------------------------------------------

    async def effective_config(
        self, purpose: str, global_values: dict[str, str], env_api_key: str
    ) -> EffectiveAiConfig:
        """Resolve one purpose to its runtime configuration.

        A mapped profile that is missing or disabled falls back to the
        default resolution (the UI sees ``source`` so it can show the
        truth). A profile WITHOUT its own key never falls back to the env
        key — an explicitly configured profile must carry its own secret.
        """
        if purpose not in PURPOSES:
            raise InvalidAiSettings(f"unknown AI purpose: {purpose}")
        purposes = await self.load_purposes()
        profile_id = purposes.get(purpose, DEFAULT_PROFILE_ID)
        provider = global_values[KEY_PROVIDER]
        if profile_id != DEFAULT_PROFILE_ID:
            row = await self._fetch_row(profile_id)
            if row is not None and row["enabled"]:
                key = self._secrets.get(profile_secret_key(profile_id))
                has_key = key is not None and key.strip() != ""
                return EffectiveAiConfig(
                    source="profile",
                    profile_id=profile_id,
                    profile_label=row["label"],
                    base_url=row["base_url"],
                    model=row["model"],
                    provider=provider,
                    api_key=key if has_key else None,
                    key_source="profile_secret" if has_key else "missing",
                )
        key = self._secrets.get(default_secret_key())
        if key is not None and key.strip() != "":
            key_source = "default_secret"
        elif env_api_key.strip():
            key = env_api_key
            key_source = "env"
        else:
            key = None
            key_source = "missing"
        return EffectiveAiConfig(
            source="default",
            profile_id=None,
            profile_label=None,
            base_url=global_values[KEY_BASE_URL],
            model=global_values[KEY_MODEL],
            provider=provider,
            api_key=key,
            key_source=key_source,
        )

    def _validate_fields(
        self, *, label: str, base_url: str, model: str
    ) -> dict[str, str]:
        try:
            clean_label = _validate_label(label)
            clean_base = _validate_base_url(base_url)
            clean_model = _validate_model(model)
        except ValueError as exc:
            raise InvalidAiSettings(str(exc)) from exc
        return {
            "label": clean_label,
            "provider": "openai_compatible",
            "base_url": clean_base,
            "model": clean_model,
        }
