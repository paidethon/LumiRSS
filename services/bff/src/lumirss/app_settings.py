"""Portable Lumi app settings (0017 Reader Power UX & Unified Settings).

Design constraints:

- lumi.sqlite stores ONE JSON document (``app.settings``) with the full
  portable settings object. There is deliberately NO per-key KV sprawl and
  NO arbitrary JSON editor: the document is defined by a strict pydantic
  model (extra keys forbidden), every field is bounded, and NaN/Infinity
  never reaches the database.
- lumi.sqlite stays a Lumi app-metadata store only. No feeds / entries /
  read state / starred / subscription data may ever live here — FreshRSS
  remains the RSS-domain source of truth.
- Secrets: none. The portable settings contain no credentials of any
  kind; browser-side translation keys are retired (0016 owns translation).
- Defaults live in code; the DB only stores user overrides. Loading is
  always safe even on a fresh or corrupted database.
"""

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from lumirss.storage import Database

SETTINGS_SCHEMA_VERSION = 1
STORAGE_KEY = "app.settings"

THEME_MODES = ("system", "light", "dark")
UI_FONT_STACKS = ("default", "sans", "serif", "mono")
UI_FONT_SIZES = (15, 16, 18, 20)
READER_FONT_FAMILIES = ("system", "sans", "serif", "mono")
READER_BACKGROUNDS = ("follow", "sepia", "warm", "paper", "mint", "custom")
READER_IMAGE_MODES = ("all", "grayscale", "hidden")
READER_TEXT_INDENTS = ("off", "2em")
READER_CHINESE_CONVERSIONS = ("off", "s2t", "t2s", "tw", "hk")
READER_CODE_HIGHLIGHTS = ("auto", "off")
READER_CODE_THEMES = (
    "auto",
    "github-light",
    "github-dark",
    "vitesse-light",
    "vitesse-dark",
)

# Continuous numeric reader ranges (0017 AD-0017-1). Steps live in the
# frontend slider definitions; the server only enforces the bounds and
# finite numbers, then normalizes onto the declared step grid.
_NUMERIC_RANGES: dict[str, tuple[float, float, float]] = {
    "readerFontSize": (12.0, 28.0, 1.0),
    "readerLineHeight": (1.2, 2.4, 0.05),
    "readerParagraphSpacing": (0.0, 2.0, 0.05),
    "readerContentWidth": (560.0, 1080.0, 20.0),
    "readerPageMargin": (12.0, 64.0, 4.0),
}

_HEX_COLOR_RE = r"^#[0-9a-fA-F]{6}$"


class InvalidAppSettings(Exception):
    """A settings value failed allow-list validation (message is browser-safe)."""


class PortableSettings(BaseModel):
    """The complete portable settings document (schema version 1).

    Strict types: booleans reject 0/1/"true"; strings reject non-strings;
    numbers reject non-numbers and NaN/Infinity. Unknown keys are rejected
    by ``extra="forbid"`` on both this model and the patch model, so
    anything not allow-listed here can never be persisted.
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)

    schemaVersion: Literal[1] = 1

    themeMode: Literal["system", "light", "dark"] = "system"
    accentColor: str = "#6d78e8"
    uiFontStack: Literal["default", "sans", "serif", "mono"] = "default"
    uiFontSize: Literal[15, 16, 18, 20] = 16
    reduceMotion: bool = False

    readerFontFamily: Literal["system", "sans", "serif", "mono"] = "system"
    readerFontSize: float = 17.0
    readerLineHeight: float = 1.85
    readerParagraphSpacing: float = 0.85
    readerContentWidth: float = 760.0
    readerPageMargin: float = 32.0
    readerBackground: Literal["follow", "sepia", "warm", "paper", "mint", "custom"] = "follow"
    readerBackgroundCustom: str = "#eef7ee"
    readerJustify: bool = False
    readerImageMode: Literal["all", "grayscale", "hidden"] = "all"
    readerTextIndent: Literal["off", "2em"] = "off"
    readerHangingPunctuation: bool = False
    readerChineseConversion: Literal["off", "s2t", "t2s", "tw", "hk"] = "off"
    readerShowReadingTime: bool = False
    readerCodeHighlight: Literal["auto", "off"] = "auto"
    readerCodeTheme: Literal[
        "auto", "github-light", "github-dark", "vitesse-light", "vitesse-dark"
    ] = "auto"
    scrollMarkUnread: bool = False

    @field_validator("accentColor", "readerBackgroundCustom")
    @classmethod
    def _hex_color(cls, value: str) -> str:
        import re

        if re.fullmatch(_HEX_COLOR_RE, value) is None:
            raise ValueError("must be a #RRGGBB hex color")
        return value.lower()

    @field_validator(
        "readerFontSize",
        "readerLineHeight",
        "readerParagraphSpacing",
        "readerContentWidth",
        "readerPageMargin",
    )
    @classmethod
    def _bounded_number(cls, value: float, info) -> float:
        minimum, maximum, step = _NUMERIC_RANGES[info.field_name]
        if value < minimum or value > maximum:
            raise ValueError(f"must be between {minimum:g} and {maximum:g}")
        # Normalize onto the step grid (absorbs float artifacts like
        # 1.8500000000000001 from JS sliders; relative to min so legacy
        # values like 0.85 stay exact on a 0.05 grid).
        steps = round((value - minimum) / step)
        normalized = minimum + steps * step
        normalized = min(maximum, max(minimum, normalized))
        return round(normalized, 3)


class PortableSettingsPatch(BaseModel):
    """PATCH /api/v1/settings body — every field optional, strict.

    Missing fields keep their current value. ``extra="forbid"`` rejects
    unknown keys loudly (422), so a smuggled key can never reach the
    store. Out-of-range / non-finite values raise InvalidAppSettings
    (400 invalid_app_settings).
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)

    themeMode: Literal["system", "light", "dark"] | None = None
    accentColor: str | None = None
    uiFontStack: Literal["default", "sans", "serif", "mono"] | None = None
    uiFontSize: Literal[15, 16, 18, 20] | None = None
    reduceMotion: bool | None = None
    readerFontFamily: Literal["system", "sans", "serif", "mono"] | None = None
    readerFontSize: float | None = None
    readerLineHeight: float | None = None
    readerParagraphSpacing: float | None = None
    readerContentWidth: float | None = None
    readerPageMargin: float | None = None
    readerBackground: Literal["follow", "sepia", "warm", "paper", "mint", "custom"] | None = None
    readerBackgroundCustom: str | None = None
    readerJustify: bool | None = None
    readerImageMode: Literal["all", "grayscale", "hidden"] | None = None
    readerTextIndent: Literal["off", "2em"] | None = None
    readerHangingPunctuation: bool | None = None
    readerChineseConversion: Literal["off", "s2t", "t2s", "tw", "hk"] | None = None
    readerShowReadingTime: bool | None = None
    readerCodeHighlight: Literal["auto", "off"] | None = None
    readerCodeTheme: Literal[
        "auto", "github-light", "github-dark", "vitesse-light", "vitesse-dark"
    ] | None = None
    scrollMarkUnread: bool | None = None

    @field_validator("accentColor", "readerBackgroundCustom")
    @classmethod
    def _hex_color(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return PortableSettings._hex_color(value)

    @field_validator(
        "readerFontSize",
        "readerLineHeight",
        "readerParagraphSpacing",
        "readerContentWidth",
        "readerPageMargin",
        mode="before",
    )
    @classmethod
    def _strict_number(cls, value: object) -> float | None:
        """JSON numbers only: accept int/float, reject strings and bools."""
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError("must be a number, not a boolean")
        if isinstance(value, int):
            return float(value)
        if isinstance(value, float):
            return value
        raise ValueError("must be a number")


def defaults() -> PortableSettings:
    """A fresh defaults document (no stored overrides)."""
    return PortableSettings()


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AppSettingsStore:
    """Typed access to the portable settings over the lumi_settings KV row."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def load(self) -> tuple[PortableSettings, bool]:
        """(merged settings, stored) — defaults for a missing/corrupt row.

        ``stored`` reports whether a document row exists at all: the client
        uses it to decide between seeding (first visit) and server-wins
        (explicit durable values).
        """
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT value FROM lumi_settings WHERE key = ?", (STORAGE_KEY,)
        )
        if row is None:
            return defaults(), False
        try:
            parsed = json.loads(row["value"])
            document = PortableSettings.model_validate(parsed)
        except (json.JSONDecodeError, ValueError):
            # Corrupted / future-schema document → safe defaults, never crash.
            return defaults(), True
        return document, True

    async def save(self, patch: PortableSettingsPatch) -> PortableSettings:
        """Validate + persist only the provided (non-None) fields."""
        current, _ = await self.load()
        merged = PortableSettings.model_validate(
            {**current.model_dump(), **patch.model_dump(exclude_unset=True)}
        )
        await self._db.execute(
            "INSERT INTO lumi_settings (key, value, updated_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (STORAGE_KEY, merged.model_dump_json(), _utc_now()),
        )
        return merged

    async def reset(self) -> PortableSettings:
        """Remove stored overrides entirely; return defaults."""
        await self._db.migrate()
        await self._db.execute(
            "DELETE FROM lumi_settings WHERE key = ?", (STORAGE_KEY,)
        )
        return defaults()
