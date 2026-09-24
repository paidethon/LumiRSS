"""Instance-level settings (P0 registration policy).

Small typed store over the control-DB ``instance_settings`` table
(migration 0089). Keys are allow-listed; values are typed by key.
The DEFAULT lives here, not in the database: an absent row means the
safe default (registration closed) for both fresh installs and
upgraded instances.
"""

import time

from lumirss.storage import Database

# Allow-list of instance settings: key -> safe default. Booleans are
# stored as "1"/"0" so the table stays debuggable.
_INSTANCE_SETTING_DEFAULTS: dict[str, str] = {
    "allow_public_registration": "0",
}


class UnknownInstanceSetting(Exception):
    """The requested key is not part of the allow-list."""


class InstanceSettingsStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, key: str) -> str:
        """Current value; the safe default when never set."""
        if key not in _INSTANCE_SETTING_DEFAULTS:
            raise UnknownInstanceSetting(key)
        row = await self._db.fetch_one(
            "SELECT value FROM instance_settings WHERE key = ?",
            (key,),
        )
        if row is None:
            return _INSTANCE_SETTING_DEFAULTS[key]
        return str(row["value"])

    async def get_bool(self, key: str) -> bool:
        return (await self.get(key)) == "1"

    async def set(self, key: str, value: str, updated_by: str | None) -> None:
        if key not in _INSTANCE_SETTING_DEFAULTS:
            raise UnknownInstanceSetting(key)
        await self._db.execute(
            "INSERT OR REPLACE INTO instance_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
            (key, value, int(time.time()), updated_by),
        )

    async def describe(self, key: str) -> dict[str, object]:
        """Value + provenance for admin UI display."""
        row = await self._db.fetch_one(
            "SELECT value, updated_at, updated_by FROM instance_settings WHERE key = ?",
            (key,),
        )
        if row is None:
            return {
                "value": _INSTANCE_SETTING_DEFAULTS[key],
                "updatedAt": None,
                "updatedBy": None,
            }
        return {
            "value": str(row["value"]),
            "updatedAt": row["updated_at"],
            "updatedBy": row["updated_by"],
        }
