"""R21 translation-engine migration — retired self-hosted LibreTranslate.

The ``libretranslate`` translation engine (self-hosted MT reached through
the BFF, including its URL/status settings keys and optional API key) was
removed. Users who still had ``translation.engine = libretranslate``
stored must not lose their setting silently: the first read of the AI
settings rewrites the engine to ``ai`` (the closest equivalent — a
server-side translation engine) and records a one-time portable marker
``translationMigratedFromLibre = true`` so the browser can show a single
"self-hosted translation was removed — pick AI or browser translation"
notice. Nothing else about the user's data changes.

Semantics (all idempotent):

- stored engine != ``libretranslate`` → zero writes, returns the input
  unchanged (fresh installs and already-migrated users never pay);
- stored engine == ``libretranslate`` →
    1. ``translation.engine`` → ``ai`` (KV upsert);
    2. the dead ``translation.libretranslate_*`` keys are deleted (the
       allow-list no longer accepts them; they are retired config, not
       user content);
    3. the portable settings document gets
       ``translationMigratedFromLibre = true`` (merged into the existing
       document — no other portable value is touched);
  then the corrected stored map is returned so the triggering read
  observes the migrated values without a second load.

Triggered from ``AiSettingsStore.load`` — every consumer of the engine
value (settings view, segment translation, privacy inventories) reads
through it, so a legacy value can never leak into runtime decisions.

All SQL is an inline literal with fully parameterized placeholders.
"""

from lumirss.util import utc_now as _utc_now

_ENGINE_KEY = "translation.engine"

# Retired allow-list keys (R21) — removed from lumi_settings when the
# migration fires. Pure config debris: no user content is deleted.
_LEGACY_KEYS = (
    "translation.libretranslate_url",
    "translation.libretranslate_status",
    "translation.libretranslate_checked_at",
    "translation.libretranslate_diagnostic",
)

_KV_UPSERT_SQL = (
    "INSERT INTO lumi_settings (key, value, updated_at) "
    "VALUES (?, ?, ?) "
    "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
    "updated_at = excluded.updated_at"
)

_KV_DELETE_SQL = "DELETE FROM lumi_settings WHERE key = ?"


async def migrate_libretranslate_engine(
    db, stored: dict[str, str]
) -> dict[str, str]:
    """Migrate a stored ``libretranslate`` engine to ``ai`` (+ marker).

    ``stored`` is the raw key/value map the caller just fetched from
    ``lumi_settings``. Returns the corrected map (legacy keys removed);
    returns the input unchanged when there is nothing to migrate.
    """
    if stored.get(_ENGINE_KEY) != "libretranslate":
        return stored
    await _set_engine_ai(db)
    corrected = {
        key: value for key, value in stored.items() if key not in _LEGACY_KEYS
    }
    corrected[_ENGINE_KEY] = "ai"
    await _set_portable_marker(db)
    return corrected


async def _set_engine_ai(db) -> None:
    await db.execute(_KV_UPSERT_SQL, (_ENGINE_KEY, "ai", _utc_now()))
    for key in _LEGACY_KEYS:
        await db.execute(_KV_DELETE_SQL, (key,))


async def _set_portable_marker(db) -> None:
    from lumirss.app_settings import AppSettingsStore, PortableSettingsPatch

    await AppSettingsStore(db).save(
        PortableSettingsPatch(translationMigratedFromLibre=True)
    )
