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
import re
from typing import Literal, NamedTuple

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

# ---- R25 云端同步扩展（原 device-local 用户偏好上云）----
# 工具栏 order 键：字符串数组透传（元素为动作 id 或隐藏占位 '-id'，
# 客户端注册表归一化是语义边界；服务端只做格式 + 容量校验）。
_TOOLBAR_ENTRY_RE = re.compile(r"^[a-z0-9-]+$")
_TOOLBAR_ORDER_MAX = 64
_TOOLBAR_ENTRY_MAX = 64

# 发音词典容量（与 Web normalizeSpeechLexicon 的 SPEECH_LEXICON_CAP 对齐）。
_SPEECH_LEXICON_MAX = 50
# 语速档位（与 Web SPEECH_RATES 对齐；float 不能进 Literal，用校验器）。
_SPEECH_RATES = (0.75, 1.0, 1.25, 1.5)

# 布局整数键边界（侧栏宽 / 时间线宽 / 视口宽度百分比）。
_INT_BOUNDS: dict[str, tuple[int, int]] = {
    "sidebarWidth": (220, 300),
    "timelineWidth": (360, 460),
    "readerContentWidthViewport": (50, 100),
}

# 过滤规则容量上限（关键词/正则由客户端归一化做语义边界；
# 服务端只做结构 + 长度校验——JS/Python 正则方言不同，不做编译校验）。
_FILTER_RULES_MAX = 256


class SpeechLexiconEntrySync(BaseModel):
    """N095：发音词典单条（{match, replace} 子串替换；只作用于朗读文本）。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)

    match: str = Field(min_length=1, max_length=256)
    replace: str = Field(default="", max_length=256)


class FilterRuleSync(BaseModel):
    """过滤规则单条（与 Web FilterRule 同一口径；feedId=null = 全局）。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)

    id: str = Field(min_length=1, max_length=64)
    keyword: str = Field(min_length=1, max_length=512)
    feedId: str | None = Field(default=None, min_length=1, max_length=256)
    type: Literal["keyword", "regex"] = "keyword"
    enabled: bool = True


def _validate_toolbar_order(values: list[str]) -> list[str]:
    """order 键透传校验：容量 + 元素格式 ^[a-z0-9-]+$（'-id' 占位合法）。"""
    if len(values) > _TOOLBAR_ORDER_MAX:
        raise ValueError(f"at most {_TOOLBAR_ORDER_MAX} entries")
    for entry in values:
        if len(entry) > _TOOLBAR_ENTRY_MAX or _TOOLBAR_ENTRY_RE.fullmatch(entry) is None:
            raise ValueError("entries must match ^[a-z0-9-]+$")
    return values


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

    # ---- R25 云端同步扩展批1：时间线与外观偏好（原 device-local） ----
    # 已读条目变暗 / 按日期分组 / 未读视图（顶栏 segmented 记忆偏好）。
    dimRead: bool = False
    groupByDate: bool = False
    unreadOnly: bool = False
    # 自定义 CSS（仅作用 .lumi-reader；64KB 上限与 Web normalize 一致）。
    customCss: str = Field(default="", max_length=64_000)
    # 当前激活的阅读预设 id（引用 readerPresets / 内置 id；'default' = 无）。
    readerPresetId: str = Field(default="default", min_length=1, max_length=64)
    # F056 暂停阅读进度记录 / F053 双语关联滚动。
    pauseReadingProgress: bool = False
    translationLinkedScroll: bool = False
    # N069 选词词典 API 地址模板（格式语义由 Web normalizeDictApiUrl 归一化；
    # 服务端只限长度；'' = 未配置）。
    dictApiUrl: str = Field(default="", max_length=512)
    # N070 纯键盘阅读定位。
    readerKeyNav: bool = False
    # 过滤规则（用户内容偏好；正则方言语义边界在客户端归一化）。
    filterRules: list[FilterRuleSync] = Field(default_factory=list, max_length=_FILTER_RULES_MAX)

    # ---- R25 云端同步扩展批2：排版扩展（R5 设备本偏好上云） ----
    # F068 正文字重档位。
    readerFontWeight: Literal[300, 400, 500, 600, 700] = 400
    # F069 图片最大宽度档位 / F070 首图破格 / F071 caption 显示模式。
    readerImageMaxWidth: Literal["100%", "75%", "60%"] = "100%"
    readerFirstImageFullBleed: bool = False
    readerCaptionMode: Literal["show", "hidden", "hover"] = "show"
    # F064 纸张质感 / F072 代码等宽字号 / F073 代码行号。
    readerPaperTexture: bool = False
    readerCodeFontSize: Literal["s", "m", "l"] = "m"
    readerCodeLineNumbers: bool = False
    # F063 护眼提醒间隔档位（0 = 关）。
    readerBreakReminderMinutes: Literal[0, 20, 30, 45, 60, 90] = 45
    # F065 宽度模式（fixed px 档 / viewport 百分比，50–100 钳制）与
    # F079 fixed 媒体清理。
    readerContentWidthMode: Literal["fixed", "viewport"] = "fixed"
    readerContentWidthViewport: int = 92
    readerStripFixedMedia: bool = True
    # N055 缩进按块类型扩展 / N056 避头尾（与已同步的 readerTextIndent /
    # readerHangingPunctuation 同属中文排版偏好）。
    readerIndentLists: bool = False
    readerIndentQuotes: bool = False
    readerLineBreakStrict: bool = False
    # 实验性词首强调 / F009 默认不加载远程图片（均为用户偏好开关）。
    readerBionic: bool = False
    readerBlockRemoteImages: bool = False

    # ---- R25 云端同步扩展批3：三栏布局偏好（用户拖拽记忆，非视口测量） ----
    sidebarWidth: int = 240  # 220–300 钳制
    sidebarCollapsed: bool = False
    timelineWidth: int = 400  # 360–460 钳制
    timelineCollapsed: bool = False

    # ---- R25 云端同步扩展批4：移动阅读交互（N052/N053 上云） ----
    # N052 阅读模式（与便携键 readerPagedMode 并存：'paged' 优先）。
    readerReadingMode: Literal["scroll", "paged"] = "scroll"
    # N053 分页点按翻页区（仅阅读模式 = 分页时生效）。
    readerTapZoneAxis: Literal["horizontal", "vertical"] = "horizontal"
    readerTapZoneSize: Literal["off", "small", "large"] = "small"

    # ---- R25 云端同步扩展批5：阅读器工具栏自定义（P07 上云） ----
    # order 键透传：元素为动作 id 或隐藏占位 '-id'（R11 申报：服务端
    # 只做 ^[a-z0-9-]+$ 格式 + 容量校验，语义归一化在客户端注册表）。
    # 服务端默认 [] =「未设置」；客户端归一化会补齐注册表缺项。
    readerToolbarDesktopOrder: list[str] = Field(default_factory=list)
    readerToolbarMobileOrder: list[str] = Field(default_factory=list)

    # ---- R25 云端同步扩展批6：朗读引擎全套（P18/NF1 上云） ----
    # 首选声音 voiceURI（'' = 自动链；声音库设备各异，URI 缺失时由
    # 客户端 pickVoice 回退，不视为错误）。
    speechVoiceURI: str = Field(default="", max_length=256)
    # 语速档位 {0.75, 1, 1.25, 1.5}（float 不能进 Literal，校验器白名单）。
    speechRate: float = 1.0
    # 睡眠定时档位（分钟；0 = 关）。
    speechSleepTimerMinutes: Literal[0, 5, 10, 15, 30] = 0
    # N094 听读内容排除（代码块/表格/脚注/图片说明/纯链接段落）。
    speechSkipCode: bool = False
    speechSkipTables: bool = False
    speechSkipFootnotes: bool = False
    speechSkipCaptions: bool = False
    speechSkipLinkOnly: bool = False
    # N095 发音词典（子串替换；语义边界在客户端朗读管线）。
    speechLexicon: list[SpeechLexiconEntrySync] = Field(
        default_factory=list, max_length=_SPEECH_LEXICON_MAX
    )
    # N097 原文译文交替听读 + 间隔档位。
    speechBilingualAlternate: bool = False
    speechBilingualGap: Literal["none", "short", "long"] = "none"
    # N093 按语言自动选声（'' = 该语言走自动链）。
    speechVoiceURIZh: str = Field(default="", max_length=256)
    speechVoiceURIEn: str = Field(default="", max_length=256)
    # N096 朗读结束模式。
    speechStopMode: Literal["article", "queue"] = "article"

    # ---- N058 阅读样式预设进 portable 同步 ----
    # 用户派生预设（内置预设不存）。每个预设自带 schemaVersion（版本
    # 标签，与前端 reader-preset-device.ts 的 PRESET_SCHEMA_VERSION 对
    # 齐）；deviceScope 属设备适用性声明，随预设同步、在应用侧守卫
    # 设备专属参数（mobile 应用 desktop-only 预设忽略宽度/栏数）。
    readerPresets: list[ReaderPresetSync] = []

    # ---- R21：自托管 LibreTranslate 翻译引擎移除的一次性迁移标记 ----
    # 服务端迁移（translation_engine_migration）把旧 engine=libretranslate
    # 改写为 ai 时置 true；前端据此给一次「自托管翻译已移除」的提示。
    # 默认 False（"0"）；非迁移用户永远是 False。
    translationMigratedFromLibre: bool = False

    @field_validator("readerToolbarDesktopOrder", "readerToolbarMobileOrder")
    @classmethod
    def _toolbar_order(cls, value: list[str]) -> list[str]:
        return _validate_toolbar_order(value)

    @field_validator("speechRate")
    @classmethod
    def _speech_rate(cls, value: float) -> float:
        if not any(value == rate for rate in _SPEECH_RATES):
            raise ValueError("must be one of 0.75, 1, 1.25, 1.5")
        return value

    # 布局/视口百分比整数键：接受 JS 侧可能带来的小数（round 归整），
    # 钳制到声明边界；布尔与字符串一律拒绝。
    @field_validator(*_INT_BOUNDS, mode="before")
    @classmethod
    def _bounded_int(cls, value: object, info) -> int:
        minimum, maximum = _INT_BOUNDS[info.field_name]
        if isinstance(value, bool):
            raise ValueError("must be an integer, not a boolean")
        if isinstance(value, float):
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError("must be finite")
            value = round(value)
        if not isinstance(value, int):
            raise ValueError("must be an integer")
        return min(maximum, max(minimum, value))

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

    # ---- R25 云端同步扩展（与 PortableSettings 同一批新增键镜像） ----
    dimRead: bool | None = None
    groupByDate: bool | None = None
    unreadOnly: bool | None = None
    customCss: str | None = Field(default=None, max_length=64_000)
    readerPresetId: str | None = Field(default=None, min_length=1, max_length=64)
    pauseReadingProgress: bool | None = None
    translationLinkedScroll: bool | None = None
    dictApiUrl: str | None = Field(default=None, max_length=512)
    readerKeyNav: bool | None = None
    filterRules: list[FilterRuleSync] | None = Field(
        default=None, max_length=_FILTER_RULES_MAX
    )

    readerFontWeight: Literal[300, 400, 500, 600, 700] | None = None
    readerImageMaxWidth: Literal["100%", "75%", "60%"] | None = None
    readerFirstImageFullBleed: bool | None = None
    readerCaptionMode: Literal["show", "hidden", "hover"] | None = None
    readerPaperTexture: bool | None = None
    readerCodeFontSize: Literal["s", "m", "l"] | None = None
    readerCodeLineNumbers: bool | None = None
    readerBreakReminderMinutes: Literal[0, 20, 30, 45, 60, 90] | None = None
    readerContentWidthMode: Literal["fixed", "viewport"] | None = None
    readerContentWidthViewport: int | None = None
    readerStripFixedMedia: bool | None = None
    readerIndentLists: bool | None = None
    readerIndentQuotes: bool | None = None
    readerLineBreakStrict: bool | None = None
    readerBionic: bool | None = None
    readerBlockRemoteImages: bool | None = None

    sidebarWidth: int | None = None
    sidebarCollapsed: bool | None = None
    timelineWidth: int | None = None
    timelineCollapsed: bool | None = None

    readerReadingMode: Literal["scroll", "paged"] | None = None
    readerTapZoneAxis: Literal["horizontal", "vertical"] | None = None
    readerTapZoneSize: Literal["off", "small", "large"] | None = None

    readerToolbarDesktopOrder: list[str] | None = Field(default=None)
    readerToolbarMobileOrder: list[str] | None = Field(default=None)

    speechVoiceURI: str | None = Field(default=None, max_length=256)
    speechRate: float | None = None
    speechSleepTimerMinutes: Literal[0, 5, 10, 15, 30] | None = None
    speechSkipCode: bool | None = None
    speechSkipTables: bool | None = None
    speechSkipFootnotes: bool | None = None
    speechSkipCaptions: bool | None = None
    speechSkipLinkOnly: bool | None = None
    speechLexicon: list[SpeechLexiconEntrySync] | None = Field(
        default=None, max_length=_SPEECH_LEXICON_MAX
    )
    speechBilingualAlternate: bool | None = None
    speechBilingualGap: Literal["none", "short", "long"] | None = None
    speechVoiceURIZh: str | None = Field(default=None, max_length=256)
    speechVoiceURIEn: str | None = Field(default=None, max_length=256)
    speechStopMode: Literal["article", "queue"] | None = None

    # R21：迁移标记允许前端确认后显式清零（一次性提示的 ack 路径）。
    translationMigratedFromLibre: bool | None = None

    # N058：预设列表整体替换（幂等 upsert 语义由客户端以 id 归并后发送）。
    readerPresets: list[ReaderPresetSync] | None = Field(default=None, max_length=_MAX_PRESETS)

    @field_validator("readerToolbarDesktopOrder", "readerToolbarMobileOrder")
    @classmethod
    def _toolbar_order(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _validate_toolbar_order(value)

    @field_validator("speechRate")
    @classmethod
    def _speech_rate(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not any(value == rate for rate in _SPEECH_RATES):
            raise ValueError("must be one of 0.75, 1, 1.25, 1.5")
        return value

    @field_validator(*_INT_BOUNDS, mode="before")
    @classmethod
    def _bounded_int(cls, value: object, info) -> object:
        if value is None:
            return None
        minimum, maximum = _INT_BOUNDS[info.field_name]
        if isinstance(value, bool):
            raise ValueError("must be an integer, not a boolean")
        if isinstance(value, float):
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError("must be finite")
            value = round(value)
        if not isinstance(value, int):
            raise ValueError("must be an integer")
        return min(maximum, max(minimum, value))

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
        "speechRate",
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




class SavedSettings(NamedTuple):
    """save() 结果：合并后的完整文档 + 显式存过的键（升序）。"""

    document: PortableSettings
    stored_keys: list[str]


class AppSettingsStore:
    """Typed access to the portable settings over the lumi_settings KV row."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def load_raw(
        self,
    ) -> tuple[PortableSettings, bool, dict[str, object] | None]:
        """(merged settings, stored, raw stored JSON dict).

        ``raw`` is the parsed stored row verbatim (None = no row; empty dict
        = row existed but was unreadable). R25: the client uses the raw key
        set to tell「explicitly stored」apart from「model default」— keys a
        newer release added after the document was written stay unset, so
        upgrading clients keep their local values instead of being clobbered
        by freshly padded defaults.
        """
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT value FROM lumi_settings WHERE key = ?", (STORAGE_KEY,)
        )
        if row is None:
            return defaults(), False, None
        try:
            raw = json.loads(row["value"])
            document = PortableSettings.model_validate(raw)
        except (json.JSONDecodeError, ValueError):
            # Corrupted / future-schema document → safe defaults, never crash.
            return defaults(), True, {}
        if not isinstance(raw, dict):
            return defaults(), True, {}
        return document, True, raw

    async def load(self) -> tuple[PortableSettings, bool]:
        """(merged settings, stored) — defaults for a missing/corrupt row.

        ``stored`` reports whether a document row exists at all: the client
        uses it to decide between seeding (first visit) and server-wins
        (explicit durable values).
        """
        document, stored, _ = await self.load_raw()
        return document, stored

    async def save(self, patch: PortableSettingsPatch) -> SavedSettings:
        """Validate + persist only the provided (non-None) fields.

        R25: the stored JSON keeps ONLY explicitly saved overrides (merged
        onto the previous raw row) instead of a full model dump. New keys
        introduced by later releases therefore stay absent until the user
        actually saves them, which is what makes the upgrade path
        (client keeps local → uploads as initial cloud value) workable.
        Legacy full-document rows keep their explicit keys as-is.
        """
        current, _, raw = await self.load_raw()
        patch_values = patch.model_dump(exclude_unset=True)
        merged = PortableSettings.model_validate({**current.model_dump(), **patch_values})
        overrides: dict[str, object] = {**(raw if raw else {}), **patch_values}
        await self._db.execute(
            "INSERT INTO lumi_settings (key, value, updated_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (STORAGE_KEY, json.dumps(overrides), _utc_now()),
        )
        return SavedSettings(merged, sorted(overrides))

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
