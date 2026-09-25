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
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from lumirss.storage import Database
from lumirss.util import utc_now as _utc_now

SETTINGS_SCHEMA_VERSION = 1
STORAGE_KEY = "app.settings"


class AppSettingsConflict(Exception):
    """0021: a PATCH carried a baseRevision that no longer matches the
    stored document — another device saved in between. Message is
    browser-safe and static."""

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
# 2026-09 移动端专项：玻璃效果 / 列表展示 / 阅读辅助 / 时间线排序 /
# 卡片滑动 / 搜索高亮（与 Web 端 AppSettings 同一批新增的 portable 键）。
GLASS_EFFECTS = ("auto", "on", "off")
LIST_DENSITIES = ("compact", "standard", "comfortable")
LIST_TIME_FORMATS = ("relative", "absolute")
TIMELINE_ORDERS = ("newest", "oldest")
CARD_SWIPE_ACTIONS = ("none", "read", "readLater", "star")

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

# N058：预设 vars 允许的键（与 Web ReaderPreset['vars'] 同一口径）；
# 数值有界，未知键拒绝（extra=forbid）——任意 JSON 绝不入库。
_PRESET_VAR_NUMERIC: dict[str, tuple[float, float]] = {
    "readerFontSize": (12.0, 28.0),
    "readerLineHeight": (1.2, 2.4),
    "readerParagraphSpacing": (0.0, 2.0),
    "readerContentWidth": (560.0, 1080.0),
    "readerColumns": (1.0, 3.0),
}
_PRESET_VAR_ENUMS: dict[str, tuple[str, ...]] = {
    "readerFontFamily": ("system", "sans", "serif", "mono"),
    "readerBackground": ("follow", "sepia", "warm", "paper", "mint", "custom"),
    "deviceScope": ("all", "desktop"),
}
_MAX_PRESETS = 50
_PRESET_VARS_MAX = 12


class ReaderPresetSync(BaseModel):
    """N058：portable 同步的单个阅读预设（版本标签 + 有界 vars）。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    schemaVersion: int = Field(ge=1, le=9)
    vars: dict[str, float | str | bool] = Field(
        default_factory=dict, max_length=_PRESET_VARS_MAX
    )

    @field_validator("vars")
    @classmethod
    def _bounded_vars(
        cls, value: dict[str, float | str | bool]
    ) -> dict[str, float | str | bool]:
        clean: dict[str, float | str | bool] = {}
        for key, raw in value.items():
            if key in _PRESET_VAR_NUMERIC:
                if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                    raise ValueError(f"{key} must be a number")
                minimum, maximum = _PRESET_VAR_NUMERIC[key]
                number = float(raw)
                if number != number or number in (float("inf"), float("-inf")):
                    raise ValueError(f"{key} must be finite")
                clean[key] = round(min(maximum, max(minimum, number)), 3)
            elif key == "readerJustify":
                if not isinstance(raw, bool):
                    raise ValueError("readerJustify must be a boolean")
                clean[key] = raw
            elif key in _PRESET_VAR_ENUMS:
                text = str(raw)
                if text not in _PRESET_VAR_ENUMS[key]:
                    raise ValueError(f"{key} has an invalid value")
                clean[key] = text
            else:
                raise ValueError(f"unknown preset var: {key}")
        return clean


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
    readLaterSort: Literal["newest", "oldest"] = "newest"

    # ---- 2026-09 移动端专项（默认值见各字段；迁移：旧文档缺键 → 默认） ----
    # P0-2：正文读到底自动标为已读（新装默认开；正文末尾哨兵 + 主动推进
    # + 前台 + 稳定停留才触发，手动未读后本次访问暂停）。
    readerAutoMarkRead: bool = True
    # P1：Liquid Glass 风格材质（auto = 支持 backdrop-filter 时启用）。
    glassEffect: Literal["auto", "on", "off"] = "auto"
    # P1：移动端左缘侧滑返回（渐进增强；关闭后仅按钮返回）。
    swipeBackGesture: bool = True
    # F01 列表密度 / F02 摘要 / F03 封面 / F04 时间格式 / F05 按来源分组。
    listDensity: Literal["compact", "standard", "comfortable"] = "standard"
    listShowSnippet: bool = True
    listShowCover: bool = True
    listTimeFormat: Literal["relative", "absolute"] = "relative"
    listGroupByFeed: bool = False
    # F06 RSS 时间线排序（服务端 keyset；切换 = 换游标重建分页）。
    # N034：新增 "received" = 按投影接收时间（服务端 ?sort=received）。
    timelineOrder: Literal["newest", "oldest", "received"] = "newest"
    # F08 卡片滑动动作（屏幕边缘以外区域的横向滑动）。
    cardSwipeAction: Literal["none", "read", "readLater", "star"] = "read"
    # F11 阅读进度 / F15 代码换行 / F17 按屏翻页 / F28 搜索高亮。
    readerShowReadingProgress: bool = True
    readerCodeWrap: bool = False
    readerPagedMode: bool = False
    searchHighlightMatches: bool = True

    # ---- N058 阅读样式预设进 portable 同步 ----
    # 用户派生预设（内置预设不存）。每个预设自带 schemaVersion（版本
    # 标签，与前端 reader-preset-device.ts 的 PRESET_SCHEMA_VERSION 对
    # 齐）；deviceScope 属设备适用性声明，随预设同步、在应用侧守卫
    # 设备专属参数（mobile 应用 desktop-only 预设忽略宽度/栏数）。
    readerPresets: list[ReaderPresetSync] = []

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
    readLaterSort: Literal["newest", "oldest"] | None = None

    readerAutoMarkRead: bool | None = None
    glassEffect: Literal["auto", "on", "off"] | None = None
    swipeBackGesture: bool | None = None
    listDensity: Literal["compact", "standard", "comfortable"] | None = None
    listShowSnippet: bool | None = None
    listShowCover: bool | None = None
    listTimeFormat: Literal["relative", "absolute"] | None = None
    listGroupByFeed: bool | None = None
    timelineOrder: Literal["newest", "oldest", "received"] | None = None
    cardSwipeAction: Literal["none", "read", "readLater", "star"] | None = None
    readerShowReadingProgress: bool | None = None
    readerCodeWrap: bool | None = None
    readerPagedMode: bool | None = None
    searchHighlightMatches: bool | None = None

    # N058：预设列表整体替换（幂等 upsert 语义由客户端以 id 归并后发送）。
    readerPresets: list[ReaderPresetSync] | None = Field(default=None, max_length=_MAX_PRESETS)

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

    async def document_revision(self) -> int:
        """Content-hash revision of the stored row (0021, ETag semantics).

        0 = nothing stored. Any save that changes the stored JSON yields a
        different revision; a no-op rewrite of identical content keeps it,
        which is safe for concurrency (nothing was actually lost).
        Computed over the raw stored value so legacy rows work unchanged.
        """
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT value FROM lumi_settings WHERE key = ?", (STORAGE_KEY,)
        )
        if row is None:
            return 0
        return revision_from_value(row["value"])


def revision_from_value(value: object) -> int:
    """Stable revision for a raw stored value (0 for None/blank)."""
    if value is None:
        return 0
    import hashlib

    digest = hashlib.sha256(str(value).encode("utf-8")).digest()
    # 48 bits: comfortably collision-free for this use AND below 2^53 so
    # the browser can hold it in a JS number without precision loss.
    return int.from_bytes(digest[:6], "big")
