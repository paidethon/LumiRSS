/** 应用设置 store — 0010 Gate A。
 *
 * 类型化客户端设置（借鉴 OrigRead-Desktop DesktopSettings 模式，inspired）：
 * 单一 interface + zustand + localStorage 单 key（lumirss-settings）持久化。
 *
 * 迁移（AC17/V11）：旧 key lumirss-theme 的数据在首次读取时并入
 * （旧 key 保留不删——兼容一个版本，0017 服务端设置落地时统一收口）。
 * 旧 key lumirss-reader-bg 已在 P14 收口：首次读取时并入并在移除后
 * 删除（loadSettings 单一路径，lib/reader-bg.ts 模块已退役）。
 * themeMode 迁入后，旧 store（store/theme.ts）改为本 store 的薄封装。
 *
 * Reader 排版（fontSize/lineHeight/contentWidth）由本 store 挂 CSS 变量
 * 到 <html>（--lumi-reader-font-size 等，Gate B 接线）。 */

import { create } from 'zustand'
import { clamp } from '../lib/clamp'
import {
  HEX_COLOR_PATTERN,
  NUMERIC_RANGES,
  PORTABLE_DEFAULTS,
  SETTING_ENUMS,
} from '../api/generated/settings-meta'
import {
  type ThemeMode,
  isThemeMode,
  resolveTheme,
  prefersDarkScheme,
  applyTheme,
} from '../lib/theme'
import {
  BUILTIN_READER_PRESETS,
  PRESET_CUSTOM_BACKGROUNDS,
  READER_FONT_STACKS,
  UI_FONT_STACKS,
  resolveReaderBackground,
  readerTextPalette,
  relativeLuminance,
  prefixCustomCss,
} from '../lib/reader-style'
import { fontFamilyName, fontIdFromUrl } from '../lib/reader-fonts'
import {
  defaultReaderToolbarOrder,
  normalizeReaderToolbarOrder,
} from '../lib/reader-toolbar'
import {
  normalizeSpeechRate,
  normalizeSpeechSleepMinutes,
  type SpeechRate,
} from '../lib/reader-speech'
import {
  isValidBgImageDataUrl,
  normalizeOverlayOpacity,
} from '../lib/reader-bg-image'

export const SETTINGS_STORAGE_KEY = 'lumirss-settings'

/** 退役旧 key（原 lib/reader-bg.ts 持有；P14 双路径收口后删除该模块，
 * 此处仅保留迁移用途的常量并在 loadSettings 中一次性收割移除）。 */
export const LEGACY_READER_BG_KEY = 'lumirss-reader-bg'

// ---- 0017：连续数值范围（AD-0017-1，min/default/max/step 唯一来源） ----
// 数值范围 + 默认值派生自 BFF PortableSettings（生成的 settings-meta），
// 前端不再手工维护第二份边界。

export interface NumericRange {
  min: number
  max: number
  step: number
  default: number
}

export type ReaderNumericKey =
  | 'readerFontSize'
  | 'readerLineHeight'
  | 'readerParagraphSpacing'
  | 'readerContentWidth'
  | 'readerPageMargin'

export const READER_NUMERIC_RANGES: Record<ReaderNumericKey, NumericRange> =
  NUMERIC_RANGES

/** 旧段距枚举 → 连续 em 值（迁移映射，AD-0017-1）。 */
export const LEGACY_PARAGRAPH_SPACING_EM: Record<string, number> = {
  compact: 0.5,
  normal: 0.85,
  loose: 1.25,
}

// ---- 类型化模型（Spec §设计规格 + 0010a Gate F 扩展 + 0017 连续数值） ----

/** 0017：字号等 Reader 数值全部连续（原 15|17|19|21 等离散档退役）。 */
export type ReaderFontSize = number
export type ReaderLineHeight = number
export type ReaderContentWidth = number
/** 0010a F6：背景扩展（+paper/mint/custom，OrigRead 双主题色板原值） */
export type ReaderBackground = 'follow' | 'sepia' | 'warm' | 'paper' | 'mint' | 'custom'
/** 字体族四档（OrigRead reader-font 栈原值，inspired） */
export type ReaderFontFamily = 'system' | 'sans' | 'serif' | 'mono'
export type ReaderParagraphSpacing = number
export type ReaderImageMode = 'all' | 'grayscale' | 'hidden'
/** UI 字体四档（同源 OrigRead 栈） */
export type UiFontStack = 'default' | 'sans' | 'serif' | 'mono'
export type UiFontSize = 15 | 16 | 18 | 20

// ---- 0012 Reader Style Deep Customization 新增 ----

/** 中文首行缩进：关闭 / 2 字符（相对单位 em，作用域限正文段落） */
export type ReaderTextIndent = 'off' | '2em'
/** 简繁转换（展示层，不改服务器数据）：原文/简→繁/繁→简/台标/港标 */
export type ReaderChineseConversion = 'off' | 's2t' | 't2s' | 'tw' | 'hk'
export type ReadLaterSort = 'newest' | 'oldest'
/** 代码高亮：自动（含 code 文章按需加载 Shiki）/ 关闭 */
export type ReaderCodeHighlight = 'auto' | 'off'

// ---- 2026-09 移动端专项（P0-2 / P1 / F01–F17 新增 portable 键） ----

/** N052：阅读模式（设备本地）：连续滚动 / 分页（CSS 多栏横向翻页）。
 * 不进 PORTABLE_KEYS——与便携键 readerPagedMode（F17 按屏平滑翻页，
 * 服务端契约保持不动）并存；normalizeSettings 做一次性迁移：
 * 旧 readerPagedMode=true 且未显式设置本键 → 'paged'。 */
export type ReaderReadingMode = 'scroll' | 'paged'
/** N053：分页点按翻页区轴向（左右 / 上下）与区域大小。 */
export type ReaderTapZoneAxis = 'horizontal' | 'vertical'
export type ReaderTapZoneSize = 'off' | 'small' | 'large'
/** P0-2：正文读到底自动标为已读 */
export type GlassEffect = 'auto' | 'on' | 'off'
/** F01：列表密度三档 */
export type ListDensity = 'compact' | 'standard' | 'comfortable'
/** F04：列表时间格式 */
export type ListTimeFormat = 'relative' | 'absolute'
/** F06：RSS 时间线排序（N034：received = 服务端按接收时间排序） */
export type TimelineOrder = 'newest' | 'oldest' | 'received'
/** F08：卡片滑动动作（非屏幕边缘区） */
export type CardSwipeAction = 'none' | 'read' | 'readLater' | 'star'

/** 自定义字体条目（IndexedDB 存储，settings 只存引用 id） */
export interface ReaderCustomFont {
  id: string
  name: string
  source: 'local' | 'url'
  /** url 模式：http/https 字体地址；local 模式为空 */
  url: string
  /** 文件元信息（仅 local，展示用） */
  fileName: string
  size: number
  createdAt: number
}

/** 过滤规则（OrigRead filter-rules.ts 镜像） */
export interface FilterRule {
  id: string
  keyword: string
  feedId: string | null // null = 全局
  type: 'keyword' | 'regex'
  enabled: boolean
}
export interface FilterStats {
  totalFiltered: number
  lastFilteredAt: number | null
  lastMatchedRule: string | null
}

/** 排版预设主题（F7：主题 = 一组阅读样式变量快照） */
export interface ReaderPreset {
  id: string
  name: string
  builtin: boolean
  vars: {
    readerFontFamily: ReaderFontFamily
    readerFontSize: ReaderFontSize
    readerLineHeight: ReaderLineHeight
    readerBackground: ReaderBackground
    readerParagraphSpacing: ReaderParagraphSpacing
    readerJustify: boolean
    /** F036 预设 v2：布局宽度 / 栏数 / 设备适用（可选，随预设存储）。 */
    readerContentWidth?: number
    readerColumns?: number
    deviceScope?: 'all' | 'desktop'
  }
}

export interface AppSettings {
  /** 通用 */
  language: 'zh-CN' // 唯一支持语言（UI 只展示简体中文；i18n 未纳入范围）
  /** 时间线行为（0010a Gate E，Folo general timeline 组 inspired） */
  dimRead: boolean
  groupByDate: boolean
  unreadOnly: boolean
  /** 实验性：默认关；正式版 planned·0017（Reader Power UX） */
  scrollMarkUnread: boolean
  /** 稍后读时间线排序（pool #14；服务器可持久化偏好） */
  readLaterSort: ReadLaterSort
  /** F045：临时显示被屏蔽条目（include_hidden 查询参数，设备本地偏好）。 */
  includeHiddenEntries: boolean
  /** F056：暂停阅读进度记录（设备本地偏好）。 */
  pauseReadingProgress: boolean
  /** F053：双语关联滚动（默认关；记忆偏好）。 */
  translationLinkedScroll: boolean
  /** 外观（0010a F1，Folo UISettings inspired） */
  accentColor: string // #RRGGBB
  uiFontSize: UiFontSize
  uiFontStack: UiFontStack
  reduceMotion: boolean
  customCss: string
  /** 阅读样式 P0（0010a F6） */
  readerFontFamily: ReaderFontFamily
  readerBackground: ReaderBackground
  readerBackgroundCustom: string // #rrggbb（custom 时生效）
  /** P14：背景图片 data URL（设备本地，绝不进 PORTABLE_KEYS / 不上传）。
   * 仅接受位图 base64 data URL，编码后 ≤ 2MB（见 lib/reader-bg-image）。 */
  readerBackgroundImage: string | null
  /** P14：背景图片上的可读性遮罩不透明度（%，0–80，默认 40）。 */
  readerBackgroundImageOverlay: number
  readerParagraphSpacing: ReaderParagraphSpacing
  readerJustify: boolean
  readerImageMode: ReaderImageMode
  /** 阅读样式 P1（0010a F7） */
  readerPresetId: string // 'default' 或用户预设 id
  readerPresets: ReaderPreset[] // 用户派生预设（内置不存）
  /** OrigRead 其余页（0010a；翻译页 0017 退役——翻译由 0016 AI 负责） */
  filterRules: FilterRule[]
  filterStats: FilterStats
  /** 原有阅读/布局 */
  themeMode: ThemeMode
  readerFontSize: ReaderFontSize
  readerLineHeight: ReaderLineHeight
  readerContentWidth: ReaderContentWidth
  /** 0017：正文页面左右边距（连续；移动端 CSS 安全钳制） */
  readerPageMargin: number
  /** 0012 Reader Style Deep Customization */
  /** 自定义字体（IndexedDB id 引用；null = 未用自定义字体） */
  readerCustomFontId: string | null
  /** 字体 URL 模式（Gate 3）：直接 http/https 指向 woff2，不落 IndexedDB */
  readerFontUrl: string | null
  readerFontUrlName: string
  /** 中文排版 */
  readerTextIndent: ReaderTextIndent
  readerHangingPunctuation: boolean
  readerChineseConversion: ReaderChineseConversion
  /** N055：首行缩进按块类型扩展（缩进量仍由 readerTextIndent 提供；
   * 默认关——只有段落缩进，列表/引用不缩进，标题/代码永不缩进）。 */
  readerIndentLists: boolean
  readerIndentQuotes: boolean
  /** N056：避头尾（line-break: strict；CSS-only 展示偏好，@supports 回退）。 */
  readerLineBreakStrict: boolean
  /** 阅读时间估算开关（ReaderHeader 弱化显示） */
  readerShowReadingTime: boolean
  /** 代码高亮 + 主题 */
  readerCodeHighlight: ReaderCodeHighlight
  readerCodeTheme: string
  /** 实验性：词首强调（Bionic-style，默认关） */
  readerBionic: boolean
  /** F009：默认不加载远程图片（device-local；本地/快照资源不受影响） */
  readerBlockRemoteImages: boolean
  /** 2026-09 移动端专项新增（默认值来自 BFF PortableSettings 生成物） */
  readerAutoMarkRead: boolean
  glassEffect: GlassEffect
  swipeBackGesture: boolean
  listDensity: ListDensity
  listShowSnippet: boolean
  listShowCover: boolean
  listTimeFormat: ListTimeFormat
  listGroupByFeed: boolean
  timelineOrder: TimelineOrder
  cardSwipeAction: CardSwipeAction
  readerShowReadingProgress: boolean
  readerCodeWrap: boolean
  readerPagedMode: boolean
  /** N052：阅读模式（设备本地；'paged' = 分页阅读，优先于 readerPagedMode）。 */
  readerReadingMode: ReaderReadingMode
  /** N053：分页点按翻页区（设备本地；仅阅读模式 = 分页时生效）。 */
  readerTapZoneAxis: ReaderTapZoneAxis
  readerTapZoneSize: ReaderTapZoneSize
  searchHighlightMatches: boolean
  /** 布局（<1024 忽略；Gate C 接线） */
  sidebarWidth: number // clamp 220–300
  sidebarCollapsed: boolean
  timelineWidth: number // clamp 360–460
  timelineCollapsed: boolean
  /** P07 阅读器工具栏自定义（设备本地，两断点各自记忆）：
   * 元素为动作 id 或隐藏占位 '-id'，格式与归一化见 lib/reader-toolbar.ts。
   * 不进 PORTABLE_KEYS——工具栏排布是设备本地偏好，不参与服务端同步。 */
  readerToolbarDesktopOrder: string[]
  readerToolbarMobileOrder: string[]
  /** P18 朗读引擎（设备本地；档位/归一化来源 lib/reader-speech）：
   * 首选声音 voiceURI（'' = 自动，pickVoice 中文优先）、语速档位、
   * 睡眠定时分钟数（0 = 关）。 */
  speechVoiceURI: string
  speechRate: SpeechRate
  speechSleepTimerMinutes: number
}

export const DEFAULT_APP_SETTINGS: AppSettings = {
  // 服务器可持久化字段：默认值 = BFF PortableSettings（生成，勿手改）
  ...PORTABLE_DEFAULTS,
  // 以下为设备本地（UI-only）字段
  language: 'zh-CN',
  dimRead: false,
  groupByDate: false,
  unreadOnly: false,
  customCss: '',
  readerPresetId: 'default',
  readerPresets: [],
  // P14：背景图片（设备本地；默认无图片，遮罩 40%）
  readerBackgroundImage: null,
  readerBackgroundImageOverlay: 40,
  filterRules: [],
  filterStats: { totalFiltered: 0, lastFilteredAt: null, lastMatchedRule: null },
  includeHiddenEntries: false,
  pauseReadingProgress: false,
  translationLinkedScroll: false,
  readerCustomFontId: null,
  readerFontUrl: null,
  readerFontUrlName: '',
  readerBionic: false,
  readerBlockRemoteImages: false,
  // N055/N056：中文排版细化（默认关——维持既有排版，不悄悄改变观感）
  readerIndentLists: false,
  readerIndentQuotes: false,
  readerLineBreakStrict: false,
  // N052/N053：阅读模式与点按翻页区（设备本地交互偏好）
  readerReadingMode: 'scroll',
  readerTapZoneAxis: 'horizontal',
  readerTapZoneSize: 'small',
  sidebarWidth: 240,
  sidebarCollapsed: false,
  timelineWidth: 400,
  timelineCollapsed: false,
  // P07：默认序 = 既有视觉序的忠实快照（registry 派生，见 lib/reader-toolbar.ts）
  readerToolbarDesktopOrder: defaultReaderToolbarOrder('desktop'),
  readerToolbarMobileOrder: defaultReaderToolbarOrder('mobile'),
  // P18 朗读引擎（设备本地）
  speechVoiceURI: '',
  speechRate: 1,
  speechSleepTimerMinutes: 0,
}

// ---- 解析 / 迁移（纯函数，可测试） ----
// 枚举值域派生自 BFF PortableSettings（生成的 settings-meta）。

const READER_BG_VALUES = SETTING_ENUMS.readerBackground
const READER_FONT_FAMILIES = SETTING_ENUMS.readerFontFamily
const IMAGE_MODES = SETTING_ENUMS.readerImageMode
const UI_FONT_STACK_VALUES = SETTING_ENUMS.uiFontStack
const UI_FONT_SIZES = SETTING_ENUMS.uiFontSize
// 0012 新增枚举表
const READER_TEXT_INDENTS = SETTING_ENUMS.readerTextIndent
const READER_CHINESE_CONVERSIONS = SETTING_ENUMS.readerChineseConversion
const READER_CODE_HIGHLIGHTS = SETTING_ENUMS.readerCodeHighlight
const READ_LATER_SORTS = SETTING_ENUMS.readLaterSort
/** Shiki 主题白名单（auto = 随 Reader 明暗切换；其余为单主题锁定） */
const READER_CODE_THEMES = SETTING_ENUMS.readerCodeTheme
// 2026-09 移动端专项枚举表（生成元数据派生）
const GLASS_EFFECTS = SETTING_ENUMS.glassEffect
const LIST_DENSITIES = SETTING_ENUMS.listDensity
const LIST_TIME_FORMATS = SETTING_ENUMS.listTimeFormat
const TIMELINE_ORDERS = SETTING_ENUMS.timelineOrder
const CARD_SWIPE_ACTIONS = SETTING_ENUMS.cardSwipeAction
// N052/N053：阅读模式与点按翻页区（设备本地，值域本地定义）
const READER_TAP_ZONE_AXES: readonly ReaderTapZoneAxis[] = ['horizontal', 'vertical']
const READER_TAP_ZONE_SIZES: readonly ReaderTapZoneSize[] = ['off', 'small', 'large']

const HEX_COLOR_RE = new RegExp(HEX_COLOR_PATTERN, 'i')

/** 字体 URL 白名单校验：仅 http/https 绝对地址（0012 Gate 3）。
 * 拒绝其它协议（javascript:/data:/file: 等）与相对路径。 */
export function isValidFontUrl(value: unknown): value is string {
  if (typeof value !== 'string') return false
  try {
    const u = new URL(value)
    return (u.protocol === 'https:' || u.protocol === 'http:') && u.hostname.length > 0
  } catch {
    return false
  }
}

/** 字体 id 校验：IndexedDB 稳定 id 格式（font- + hex hash）或 null。 */
function pickFontId(value: unknown): string | null {
  return typeof value === 'string' && /^font-[0-9a-f]{8,64}$/.test(value) ? value : null
}

function pickHexColor(value: unknown, fallback: string): string {
  return typeof value === 'string' && HEX_COLOR_RE.test(value.trim())
    ? value.trim().toLowerCase()
    : fallback
}

function pickString<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback
}

/** 连续数值吸附：四舍五入到 step 网格并钳制到 [min, max]（0017）。
 * 相对 min 计算步数，避免浮点步长累计漂移（0.85/0.05 等边界值稳定）。 */
export function snapReaderNumber(key: ReaderNumericKey, value: number): number {
  const { min, max, step } = READER_NUMERIC_RANGES[key]
  const steps = Math.round((value - min) / step)
  const snapped = min + steps * step
  return Math.min(max, Math.max(min, Number(snapped.toFixed(3))))
}

/** Reader 连续数值归一化（0017 迁移）：
 * - number：吸附到连续网格（旧离散值 15/17/19/21、1.65/1.85/2.05、
 *   680/760/900 都在新范围内，视觉无变化）；
 * - 旧段距字符串枚举：compact/normal/loose → 0.5/0.85/1.25；
 * - 其它非法值：回退默认。 */
function pickReaderNumber(key: ReaderNumericKey, value: unknown): number {
  const fallback = READER_NUMERIC_RANGES[key].default
  if (typeof value === 'number' && Number.isFinite(value)) {
    return snapReaderNumber(key, value)
  }
  if (key === 'readerParagraphSpacing' && typeof value === 'string') {
    const mapped = LEGACY_PARAGRAPH_SPACING_EM[value]
    if (mapped !== undefined) return mapped
  }
  return fallback
}

/** 过滤规则归一化（F3）：逐条校验 + 去重（feedId,type,keyword 小写语义）。 */
function normalizeFilterRules(raw: unknown): FilterRule[] {
  if (!Array.isArray(raw)) return []
  const seen = new Set<string>()
  const rules: FilterRule[] = []
  for (const item of raw) {
    if (typeof item !== 'object' || item === null) continue
    const r = item as Record<string, unknown>
    const keyword = typeof r.keyword === 'string' ? r.keyword.trim() : ''
    const type = r.type === 'regex' ? 'regex' : 'keyword'
    if (!keyword) continue
    // regex 必须可编译（OrigRead 同语义；非法规则丢弃而非崩掉整个设置）
    if (type === 'regex') {
      try {
        new RegExp(keyword, 'i')
      } catch {
        continue
      }
    }
    const dedupeKey = `${String(r.feedId ?? 'null')}|${type}|${keyword.toLowerCase()}`
    if (seen.has(dedupeKey)) continue
    seen.add(dedupeKey)
    rules.push({
      id: typeof r.id === 'string' && r.id ? r.id : crypto.randomUUID(),
      keyword,
      feedId: typeof r.feedId === 'string' && r.feedId ? r.feedId : null,
      type,
      enabled: typeof r.enabled === 'boolean' ? r.enabled : true,
    })
  }
  return rules
}

function normalizePresets(raw: unknown): ReaderPreset[] {
  if (!Array.isArray(raw)) return []
  const out: ReaderPreset[] = []
  const ids = new Set<string>(BUILTIN_READER_PRESETS.map((p) => p.id))
  const widthRange = READER_NUMERIC_RANGES.readerContentWidth
  for (const item of raw) {
    if (typeof item !== 'object' || item === null) continue
    const p = item as Record<string, unknown>
    const v = (p.vars ?? {}) as Record<string, unknown>
    const id = typeof p.id === 'string' && p.id && !ids.has(p.id) ? p.id : null
    const name = typeof p.name === 'string' && p.name.trim() ? p.name.trim().slice(0, 32) : null
    if (!id || !name) continue
    ids.add(id)
    // F036 v2 字段：非法/缺失 → 不写入该键（与「可选扩展」语义一致）。
    const v2: Partial<ReaderPreset['vars']> = {}
    if (typeof v.readerContentWidth === 'number') {
      v2.readerContentWidth = clamp(v.readerContentWidth, widthRange.min, widthRange.max)
    }
    if (typeof v.readerColumns === 'number') {
      v2.readerColumns = clamp(v.readerColumns, 1, 3)
    }
    if (v.deviceScope === 'desktop' || v.deviceScope === 'all') {
      v2.deviceScope = v.deviceScope
    }
    out.push({
      id,
      name,
      builtin: false,
      vars: {
        readerFontFamily: pickString(v.readerFontFamily, READER_FONT_FAMILIES, 'system'),
        readerFontSize: pickReaderNumber('readerFontSize', v.readerFontSize),
        readerLineHeight: pickReaderNumber('readerLineHeight', v.readerLineHeight),
        readerBackground: pickString(v.readerBackground, READER_BG_VALUES, 'follow'),
        readerParagraphSpacing: pickReaderNumber('readerParagraphSpacing', v.readerParagraphSpacing),
        readerJustify: v.readerJustify === true,
        ...v2,
      },
    })
  }
  return out
}

function pickNumber<T extends number>(value: unknown, allowed: readonly T[], fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback
}

function pickBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback
}

/** N052：阅读模式归一化 + 一次性迁移。显式合法值优先；未显式设置本键
 * 且旧 readerPagedMode（F17 按屏翻页）= true → 迁移为 'paged'（分页）；
 * 其余回退默认 'scroll'。 */
function pickReadingMode(value: unknown, legacyPagedMode: unknown): ReaderReadingMode {
  if (value === 'scroll' || value === 'paged') return value
  if (value === undefined && legacyPagedMode === true) return 'paged'
  return DEFAULT_APP_SETTINGS.readerReadingMode
}

/** 把任意（不可信的）持久化 JSON 归一化为合法 AppSettings：
 * 逐字段校验，非法值回退默认；未知字段丢弃。 */
export function normalizeSettings(raw: unknown): AppSettings {
  const source = (typeof raw === 'object' && raw !== null ? raw : {}) as Record<string, unknown>
  return {
    language: source.language === 'zh-CN' ? 'zh-CN' : DEFAULT_APP_SETTINGS.language,
    dimRead: pickBoolean(source.dimRead, DEFAULT_APP_SETTINGS.dimRead),
    groupByDate: pickBoolean(source.groupByDate, DEFAULT_APP_SETTINGS.groupByDate),
    unreadOnly: pickBoolean(source.unreadOnly, DEFAULT_APP_SETTINGS.unreadOnly),
    scrollMarkUnread: pickBoolean(
      source.scrollMarkUnread,
      DEFAULT_APP_SETTINGS.scrollMarkUnread,
    ),
    readLaterSort: pickString(
      source.readLaterSort,
      READ_LATER_SORTS,
      DEFAULT_APP_SETTINGS.readLaterSort,
    ),
    accentColor: pickHexColor(source.accentColor, DEFAULT_APP_SETTINGS.accentColor),
    uiFontSize: pickNumber(source.uiFontSize, UI_FONT_SIZES, DEFAULT_APP_SETTINGS.uiFontSize),
    uiFontStack: pickString(source.uiFontStack, UI_FONT_STACK_VALUES, DEFAULT_APP_SETTINGS.uiFontStack),
    reduceMotion: pickBoolean(source.reduceMotion, DEFAULT_APP_SETTINGS.reduceMotion),
    customCss: typeof source.customCss === 'string' ? source.customCss.slice(0, 64_000) : '',
    readerFontFamily: pickString(
      source.readerFontFamily,
      READER_FONT_FAMILIES,
      DEFAULT_APP_SETTINGS.readerFontFamily,
    ),
    readerBackground: READER_BG_VALUES.includes(source.readerBackground as ReaderBackground)
      ? (source.readerBackground as ReaderBackground)
      : DEFAULT_APP_SETTINGS.readerBackground,
    readerBackgroundCustom: pickHexColor(
      source.readerBackgroundCustom,
      DEFAULT_APP_SETTINGS.readerBackgroundCustom,
    ),
    // P14：图片 data URL 校验（位图 MIME + base64 + ≤2MB）；损坏值丢弃
    readerBackgroundImage: isValidBgImageDataUrl(source.readerBackgroundImage)
      ? source.readerBackgroundImage
      : null,
    readerBackgroundImageOverlay: normalizeOverlayOpacity(
      source.readerBackgroundImageOverlay,
    ),
    readerParagraphSpacing: pickReaderNumber('readerParagraphSpacing', source.readerParagraphSpacing),
    readerJustify: pickBoolean(source.readerJustify, DEFAULT_APP_SETTINGS.readerJustify),
    readerImageMode: pickString(source.readerImageMode, IMAGE_MODES, DEFAULT_APP_SETTINGS.readerImageMode),
    readerPresetId:
      typeof source.readerPresetId === 'string' &&
      (source.readerPresetId === 'default' ||
        BUILTIN_READER_PRESETS.some((p) => p.id === source.readerPresetId) ||
        normalizePresets(source.readerPresets).some((p) => p.id === source.readerPresetId))
        ? source.readerPresetId
        : 'default',
    readerPresets: normalizePresets(source.readerPresets),
    includeHiddenEntries: pickBoolean(source.includeHiddenEntries, false),
    pauseReadingProgress: pickBoolean(source.pauseReadingProgress, false),
    translationLinkedScroll: pickBoolean(source.translationLinkedScroll, false),
    filterRules: normalizeFilterRules(source.filterRules),
    filterStats: {
      totalFiltered:
        typeof (source.filterStats as Record<string, unknown> | undefined)?.totalFiltered === 'number'
          ? (source.filterStats as Record<string, unknown>).totalFiltered as number
          : 0,
      lastFilteredAt:
        typeof (source.filterStats as Record<string, unknown> | undefined)?.lastFilteredAt === 'number'
          ? (source.filterStats as Record<string, unknown>).lastFilteredAt as number
          : null,
      lastMatchedRule:
        typeof (source.filterStats as Record<string, unknown> | undefined)?.lastMatchedRule === 'string'
          ? (source.filterStats as Record<string, unknown>).lastMatchedRule as string
          : null,
    },
    // 旧 rsshubSettings（浏览器侧参考清单）已退役：白名单外键自然丢弃
    themeMode: isThemeMode(source.themeMode)
      ? source.themeMode
      : DEFAULT_APP_SETTINGS.themeMode,
    readerFontSize: pickReaderNumber('readerFontSize', source.readerFontSize),
    readerLineHeight: pickReaderNumber('readerLineHeight', source.readerLineHeight),
    readerContentWidth: pickReaderNumber('readerContentWidth', source.readerContentWidth),
    readerPageMargin: pickReaderNumber('readerPageMargin', source.readerPageMargin),
    // 0012：逐字段校验，非法值回退默认（corrupted settings 不致启动失败）
    readerCustomFontId: pickFontId(source.readerCustomFontId),
    readerFontUrl: isValidFontUrl(source.readerFontUrl) ? source.readerFontUrl : null,
    readerFontUrlName:
      typeof source.readerFontUrlName === 'string'
        ? source.readerFontUrlName.trim().slice(0, 64)
        : '',
    readerTextIndent: pickString(
      source.readerTextIndent,
      READER_TEXT_INDENTS,
      DEFAULT_APP_SETTINGS.readerTextIndent,
    ),
    readerHangingPunctuation: pickBoolean(
      source.readerHangingPunctuation,
      DEFAULT_APP_SETTINGS.readerHangingPunctuation,
    ),
    // N055/N056：缩进扩展与避头尾（逐字段校验，非法值回退默认）
    readerIndentLists: pickBoolean(source.readerIndentLists, DEFAULT_APP_SETTINGS.readerIndentLists),
    readerIndentQuotes: pickBoolean(
      source.readerIndentQuotes,
      DEFAULT_APP_SETTINGS.readerIndentQuotes,
    ),
    readerLineBreakStrict: pickBoolean(
      source.readerLineBreakStrict,
      DEFAULT_APP_SETTINGS.readerLineBreakStrict,
    ),
    readerChineseConversion: pickString(
      source.readerChineseConversion,
      READER_CHINESE_CONVERSIONS,
      DEFAULT_APP_SETTINGS.readerChineseConversion,
    ),
    readerShowReadingTime: pickBoolean(
      source.readerShowReadingTime,
      DEFAULT_APP_SETTINGS.readerShowReadingTime,
    ),
    readerCodeHighlight: pickString(
      source.readerCodeHighlight,
      READER_CODE_HIGHLIGHTS,
      DEFAULT_APP_SETTINGS.readerCodeHighlight,
    ),
    readerCodeTheme: pickString(
      source.readerCodeTheme,
      READER_CODE_THEMES,
      DEFAULT_APP_SETTINGS.readerCodeTheme,
    ),
    readerBionic: pickBoolean(source.readerBionic, DEFAULT_APP_SETTINGS.readerBionic),
    readerBlockRemoteImages: pickBoolean(
      source.readerBlockRemoteImages,
      DEFAULT_APP_SETTINGS.readerBlockRemoteImages,
    ),
    // 2026-09 移动端专项：逐字段校验（枚举回退默认；旧文档缺键 → 默认值）
    readerAutoMarkRead: pickBoolean(
      source.readerAutoMarkRead,
      DEFAULT_APP_SETTINGS.readerAutoMarkRead,
    ),
    glassEffect: pickString(source.glassEffect, GLASS_EFFECTS, DEFAULT_APP_SETTINGS.glassEffect),
    swipeBackGesture: pickBoolean(
      source.swipeBackGesture,
      DEFAULT_APP_SETTINGS.swipeBackGesture,
    ),
    listDensity: pickString(source.listDensity, LIST_DENSITIES, DEFAULT_APP_SETTINGS.listDensity),
    listShowSnippet: pickBoolean(
      source.listShowSnippet,
      DEFAULT_APP_SETTINGS.listShowSnippet,
    ),
    listShowCover: pickBoolean(source.listShowCover, DEFAULT_APP_SETTINGS.listShowCover),
    listTimeFormat: pickString(
      source.listTimeFormat,
      LIST_TIME_FORMATS,
      DEFAULT_APP_SETTINGS.listTimeFormat,
    ),
    listGroupByFeed: pickBoolean(
      source.listGroupByFeed,
      DEFAULT_APP_SETTINGS.listGroupByFeed,
    ),
    timelineOrder: pickString(
      source.timelineOrder,
      TIMELINE_ORDERS,
      DEFAULT_APP_SETTINGS.timelineOrder,
    ),
    cardSwipeAction: pickString(
      source.cardSwipeAction,
      CARD_SWIPE_ACTIONS,
      DEFAULT_APP_SETTINGS.cardSwipeAction,
    ),
    readerShowReadingProgress: pickBoolean(
      source.readerShowReadingProgress,
      DEFAULT_APP_SETTINGS.readerShowReadingProgress,
    ),
    readerCodeWrap: pickBoolean(source.readerCodeWrap, DEFAULT_APP_SETTINGS.readerCodeWrap),
    readerPagedMode: pickBoolean(source.readerPagedMode, DEFAULT_APP_SETTINGS.readerPagedMode),
    // N052/N053：阅读模式（含 F17 → 分页的一次性迁移）与点按翻页区
    readerReadingMode: pickReadingMode(source.readerReadingMode, source.readerPagedMode),
    readerTapZoneAxis: pickString(
      source.readerTapZoneAxis,
      READER_TAP_ZONE_AXES,
      DEFAULT_APP_SETTINGS.readerTapZoneAxis,
    ),
    readerTapZoneSize: pickString(
      source.readerTapZoneSize,
      READER_TAP_ZONE_SIZES,
      DEFAULT_APP_SETTINGS.readerTapZoneSize,
    ),
    searchHighlightMatches: pickBoolean(
      source.searchHighlightMatches,
      DEFAULT_APP_SETTINGS.searchHighlightMatches,
    ),
    sidebarWidth: clamp(
      typeof source.sidebarWidth === 'number' ? source.sidebarWidth : DEFAULT_APP_SETTINGS.sidebarWidth,
      220,
      300,
    ),
    sidebarCollapsed:
      typeof source.sidebarCollapsed === 'boolean'
        ? source.sidebarCollapsed
        : DEFAULT_APP_SETTINGS.sidebarCollapsed,
    timelineWidth: clamp(
      typeof source.timelineWidth === 'number' ? source.timelineWidth : DEFAULT_APP_SETTINGS.timelineWidth,
      360,
      460,
    ),
    timelineCollapsed:
      typeof source.timelineCollapsed === 'boolean'
        ? source.timelineCollapsed
        : DEFAULT_APP_SETTINGS.timelineCollapsed,
    // P07：工具栏排布逐项归一化（去重 / 丢未知 / 补缺项 / 锁定收藏与更多）
    readerToolbarDesktopOrder: normalizeReaderToolbarOrder(
      source.readerToolbarDesktopOrder,
      'desktop',
    ),
    readerToolbarMobileOrder: normalizeReaderToolbarOrder(
      source.readerToolbarMobileOrder,
      'mobile',
    ),
    // P18 朗读引擎：档位外值回退默认（声音 URI 截断防滥用）
    speechVoiceURI:
      typeof source.speechVoiceURI === 'string'
        ? source.speechVoiceURI.slice(0, 256)
        : DEFAULT_APP_SETTINGS.speechVoiceURI,
    speechRate: normalizeSpeechRate(source.speechRate),
    speechSleepTimerMinutes: normalizeSpeechSleepMinutes(source.speechSleepTimerMinutes),
  }
}

/** 旧 lumirss-reader-bg key（lib/reader-bg.ts 退役遗留；P14 收口）：
 * 值合法且当前 readerBackground 仍为默认（视为未设置）时并入，
 * 然后无论如何移除旧 key——单一事实源收口到 lumirss-settings。 */
function importLegacyReaderBg(storage: Storage, settings: AppSettings): AppSettings {
  const legacy = storage.getItem(LEGACY_READER_BG_KEY)
  if (legacy !== null) {
    if (
      settings.readerBackground === DEFAULT_APP_SETTINGS.readerBackground &&
      READER_BG_VALUES.includes(legacy as ReaderBackground)
    ) {
      settings.readerBackground = legacy as ReaderBackground
    }
    storage.removeItem(LEGACY_READER_BG_KEY)
  }
  return settings
}

/** 首次加载：读新 key；不存在则从旧 key（theme/reader-bg）迁移。 */
export function loadSettings(storage: Storage | null): AppSettings {
  if (storage === null) return { ...DEFAULT_APP_SETTINGS }
  try {
    const raw = storage.getItem(SETTINGS_STORAGE_KEY)
    if (raw !== null) {
      // P14：新 key 已存在时同样收割/清除旧 reader-bg key（一次性迁移）
      return importLegacyReaderBg(storage, normalizeSettings(JSON.parse(raw)))
    }
    // 迁移路径：旧 key 数据并入默认值
    const migrated = { ...DEFAULT_APP_SETTINGS }
    const oldTheme = storage.getItem('lumirss-theme')
    if (isThemeMode(oldTheme)) migrated.themeMode = oldTheme
    const oldReaderBg = storage.getItem(LEGACY_READER_BG_KEY)
    if (READER_BG_VALUES.includes(oldReaderBg as ReaderBackground)) {
      migrated.readerBackground = oldReaderBg as ReaderBackground
    }
    storage.removeItem(LEGACY_READER_BG_KEY)
    return migrated
  } catch {
    return { ...DEFAULT_APP_SETTINGS }
  }
}

export function persistSettings(storage: Storage | null, settings: AppSettings): void {
  if (storage === null) return
  try {
    storage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings))
  } catch {
    /* 写失败不影响本会话 */
  }
}

/** Reader 排版/配色 CSS 变量映射（applyReaderTypography 与设置页实时
 * 预览共用同一映射，保证「预览即所得」）。follow 模式不含背景调色板
 * ——消费端继承 tokens.css 的主题默认值。 */
export function readerTypographyVars(settings: AppSettings): Record<string, string> {
  // 0010a F6：字体族 / 段距 / 对齐；0012：自定义字体优先于档位栈
  //（字体未注册完成时 CSS 自动回退档位栈，不白屏）
  let customFamily: string | null = null
  if (settings.readerCustomFontId !== null) {
    customFamily = fontFamilyName(settings.readerCustomFontId)
  } else if (settings.readerFontUrl !== null) {
    customFamily = fontFamilyName(fontIdFromUrl(settings.readerFontUrl))
  }
  const baseStack = READER_FONT_STACKS[settings.readerFontFamily]
  const vars: Record<string, string> = {
    '--lumi-reader-font-size': `${settings.readerFontSize}px`,
    '--lumi-reader-line-height': String(settings.readerLineHeight),
    '--lumi-reader-content-width': `${settings.readerContentWidth}px`,
    '--lumi-reader-font-family':
      customFamily !== null ? `"${customFamily}", ${baseStack}` : baseStack,
    '--lumi-reader-paragraph-spacing': `${settings.readerParagraphSpacing}em`,
    '--lumi-reader-page-margin': `${settings.readerPageMargin}px`,
    '--lumi-reader-text-align': settings.readerJustify ? 'justify' : 'start',
    // 0012 Gate 4：中文首行缩进相对单位（标点悬挂走 data 属性，见下）
    '--lumi-reader-text-indent': settings.readerTextIndent === '2em' ? '2em' : '0',
  }

  // 预设驱动的 custom 背景（AMOLED/高对比等内置预设携带的背景）
  const customBg =
    settings.readerPresetId in PRESET_CUSTOM_BACKGROUNDS
      ? PRESET_CUSTOM_BACKGROUNDS[settings.readerPresetId]
      : settings.readerBackgroundCustom
  const isDark = resolveTheme(settings.themeMode, prefersDarkScheme()) === 'dark'
  const bgHex = resolveReaderBackground(settings.readerBackground, customBg, isDark)
  if (bgHex !== null) {
    const palette = readerTextPalette(bgHex)
    vars['--lumi-reader-bg'] = bgHex
    vars['--lumi-reader-text'] = palette.text
    vars['--lumi-reader-heading'] = palette.heading
    vars['--lumi-reader-muted'] = palette.muted
    vars['--lumi-reader-border'] = palette.border
    vars['--lumi-reader-link'] = palette.link
  }
  return vars
}

/** 背景调色板变量集合（follow 模式下这些键需从 root 移除以回落主题默认）。 */
const READER_BG_PALETTE_VARS = [
  '--lumi-reader-bg',
  '--lumi-reader-text',
  '--lumi-reader-heading',
  '--lumi-reader-muted',
  '--lumi-reader-border',
  '--lumi-reader-link',
] as const

/** Reader 排版 CSS 变量挂载（Gate B 由 Reader 消费；此处为挂载逻辑）。 */
export function applyReaderTypography(settings: AppSettings): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  const vars = readerTypographyVars(settings)
  for (const [key, value] of Object.entries(vars)) {
    root.style.setProperty(key, value)
  }
  // follow（未解析背景）→ 移除调色板回落 tokens 默认
  for (const key of READER_BG_PALETTE_VARS) {
    if (!(key in vars)) root.style.removeProperty(key)
  }

  // 0017：图片模式：灰度/隐藏由 .article-content img 消费
  root.dataset.readerImages = settings.readerImageMode

  // 0012 Gate 4：标点悬挂 progressive enhancement —— CSS 侧用
  // @supports 包裹；简繁转换标记（展示层 transform，ArticleContent 消费）
  root.dataset.readerHangingPunctuation = settings.readerHangingPunctuation ? 'true' : 'false'
  root.dataset.readerChineseConversion = settings.readerChineseConversion

  // NE1 N055/N056：缩进按块类型扩展 + 避头尾（CSS 规则在 index.css；
  // 缩进量仍由 --lumi-reader-text-indent 提供，off 时以下全部自然失效；
  // 标点悬挂保持独立设置，互不依赖）。
  root.dataset.readerIndentLists = settings.readerIndentLists ? 'true' : 'false'
  root.dataset.readerIndentQuotes = settings.readerIndentQuotes ? 'true' : 'false'
  root.dataset.readerLineBreakStrict = settings.readerLineBreakStrict ? 'true' : 'false'

  // P14：背景图片分层（设备本地 data URL；遮罩强度 0–0.8 由
  // index.css .lumi-reader-bg-image 消费——图片上叠 reader 背景色遮罩）。
  // 无图片时移除变量：图层为 none + 全透明遮罩，视觉零变化。
  if (settings.readerBackgroundImage !== null) {
    root.style.setProperty(
      '--lumi-reader-bg-image',
      `url("${settings.readerBackgroundImage}")`,
    )
    root.style.setProperty(
      '--lumi-reader-bg-overlay',
      String(settings.readerBackgroundImageOverlay / 100),
    )
  } else {
    root.style.removeProperty('--lumi-reader-bg-image')
    root.style.removeProperty('--lumi-reader-bg-overlay')
  }
}

/** 0010a F1：外观副作用（accent 派生色 + UI 字号/字体 + 动效）。 */
const CUSTOM_CSS_STYLE_ID = 'lumi-custom-css'

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function mix(hex: string, target: [number, number, number], ratio: number): string {
  const [r, g, b] = hexToRgb(hex)
  const m = (v: number, t: number) => Math.round(v + (t - v) * ratio)
  return `rgb(${m(r, target[0])}, ${m(g, target[1])}, ${m(b, target[2])})`
}

/** accent 背景上可读的前景（白 / 近黑）。
 * 与 reader-style 同一 WCAG 约定：相对亮度 < 0.42 视作深色背景 → 白字；
 * 否则（亮色/黄色 accent）→ 近黑字。保留默认中深 accent 的白字观感，
 * 仅修正亮色自定义 accent 上白字不可读的问题。 */
function readableOnAccent(bgHex: string): string {
  return relativeLuminance(bgHex) < 0.42 ? '#ffffff' : '#1c1c1e'
}

export function applyAppearance(settings: AppSettings): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement

  // accent + 派生（hover/pressed 向黑收敛 6%/12%；soft 是 12% 透明混白/混黑）
  const hex = settings.accentColor
  root.style.setProperty('--lumi-accent', hex)
  root.style.setProperty('--lumi-accent-hover', mix(hex, [0, 0, 0], 0.08))
  root.style.setProperty('--lumi-accent-pressed', mix(hex, [0, 0, 0], 0.16))
  const isDark = resolveTheme(settings.themeMode, prefersDarkScheme()) === 'dark'
  root.style.setProperty('--lumi-accent-soft', mix(hex, isDark ? [24, 24, 26] : [255, 255, 255], 0.86))
  // AUDIT（accent 对比）：自定义亮色 accent 上白字不可读。按 WCAG
  // 相对亮度选对比更高的前景（白 / 近黑），复用现有 relativeLuminance。
  root.style.setProperty('--lumi-accent-contrast', readableOnAccent(hex))

  // 全局字号（root rem 缩放，Folo 同方案）
  root.style.fontSize = `${settings.uiFontSize}px`

  // UI 字体
  root.style.setProperty('--lumi-font-sans', UI_FONT_STACKS[settings.uiFontStack] ?? 'var(--lumi-font-default)')

  // 减少动效
  if (settings.reduceMotion) root.dataset.motionReduce = 'true'
  else delete root.dataset.motionReduce

  // 自定义 CSS（F7，AC14：仅作用于 .lumi-reader）
  let styleEl = document.getElementById(CUSTOM_CSS_STYLE_ID) as HTMLStyleElement | null
  const prefixed = settings.customCss.trim() ? prefixCustomCss(settings.customCss) : ''
  if (prefixed !== null && prefixed !== '') {
    if (!styleEl) {
      styleEl = document.createElement('style')
      styleEl.id = CUSTOM_CSS_STYLE_ID
      document.head.appendChild(styleEl)
    }
    styleEl.textContent = prefixed
  } else if (styleEl) {
    styleEl.remove()
  }
}

// ---- Store ----

/** 0017：server-durable（portable）设置键白名单（AD-0017-3）。
 * 这些键参与 /api/v1/settings 同步；其余设置是设备本地状态。
 * 键集合派生自 BFF PortableSettings（生成元数据的键即服务端接受的键）。 */
export const PORTABLE_KEYS = Object.keys(
  PORTABLE_DEFAULTS,
) as (keyof typeof PORTABLE_DEFAULTS & keyof AppSettings)[]

export type PortableKey = (typeof PORTABLE_KEYS)[number]

export type PortableValues = Record<PortableKey, string | number | boolean>

/** 从完整设置中提取 server 同步子集（数值去浮点噪声，AD-0017-2）。 */
export function portableSettings(settings: AppSettings): PortableValues {
  const out = {} as PortableValues
  for (const key of PORTABLE_KEYS) {
    const value = settings[key]
    out[key] = typeof value === 'number' ? Number(value.toFixed(3)) : value
  }
  return out
}

/** 把 server 返回的 portable 值映射为 store patch（未知键丢弃）。 */
export function portableToPatch(values: Record<string, unknown>): Partial<AppSettings> {
  const patch: Record<string, unknown> = {}
  for (const key of PORTABLE_KEYS) {
    if (key in values) patch[key] = values[key]
  }
  return patch as Partial<AppSettings>
}

/** 「恢复默认阅读设置」只触及的 Reader 键（不动用户预设/自定义字体资产）。 */
const RESET_READER_KEYS: readonly (keyof AppSettings)[] = [
  'readerFontFamily',
  'readerFontSize',
  'readerLineHeight',
  'readerParagraphSpacing',
  'readerContentWidth',
  'readerPageMargin',
  'readerBackground',
  'readerBackgroundCustom',
  // P14：恢复默认阅读设置时一并清除背景图片与遮罩
  'readerBackgroundImage',
  'readerBackgroundImageOverlay',
  'readerJustify',
  'readerImageMode',
  'readerTextIndent',
  // N055/N056：缩进扩展与避头尾属排版项，随「恢复默认阅读设置」一并还原
  'readerIndentLists',
  'readerIndentQuotes',
  'readerLineBreakStrict',
  'readerHangingPunctuation',
  'readerChineseConversion',
  'readerShowReadingTime',
  'readerCodeHighlight',
  'readerCodeTheme',
  'readerBionic',
  'readerBlockRemoteImages',
  'scrollMarkUnread',
  'readLaterSort',
]

interface AppSettingsState {
  settings: AppSettings
  /** 局部更新（借鉴 OrigRead Patch 模式）：合并 + 归一化 + 持久化 +
   *  副作用（主题/排版 CSS 变量同步）。 */
  update: (patch: Partial<AppSettings>) => void
  /** 重置为默认（数据控制页「恢复默认设置」用）。 */
  reset: () => void
  /** 0017：只重置 Reader 相关设置为默认（阅读设置页「恢复默认」）。 */
  resetReader: () => void
}

function storage(): Storage | null {
  return typeof localStorage === 'undefined' ? null : localStorage
}

/** 应用全部"有 DOM 副作用"的设置（主题/排版/外观）。 */
function applySideEffects(settings: AppSettings): void {
  if (typeof document === 'undefined') return
  applyTheme(document.documentElement, resolveTheme(settings.themeMode, prefersDarkScheme()))
  applyReaderTypography(settings)
  applyAppearance(settings)
}

export const useAppSettings = create<AppSettingsState>((set) => ({
  settings: loadSettings(storage()),
  update: (patch) => {
    const next = normalizeSettings({ ...useAppSettings.getState().settings, ...patch })
    persistSettings(storage(), next)
    applySideEffects(next)
    set({ settings: next })
  },
  reset: () => {
    const next = { ...DEFAULT_APP_SETTINGS }
    persistSettings(storage(), next)
    applySideEffects(next)
    set({ settings: next })
  },
  resetReader: () => {
    const patch: Partial<AppSettings> = {}
    for (const key of RESET_READER_KEYS) {
      ;(patch as Record<string, unknown>)[key] = DEFAULT_APP_SETTINGS[key]
    }
    const next = normalizeSettings({ ...useAppSettings.getState().settings, ...patch })
    persistSettings(storage(), next)
    applySideEffects(next)
    set({ settings: next })
  },
}))

/** 启动路径（main.tsx 调一次）：加载并把副作用应用到 DOM。 */
export function initAppSettings(): void {
  applySideEffects(useAppSettings.getState().settings)
}

/** AUDIT-008：规范主题系统监听（取代旧 store/theme.ts 的 watchSystemTheme）。
 *
 * OS 偏好变化时，仅当规范 themeMode === 'system' 才重新应用主题；显式
 * light/dark 绝不被 OS 变化覆盖。只挂一次监听（幂等），jsdom/SSR 安全。 */
let systemThemeWatcherAttached = false
export function watchSystemTheme(): void {
  if (systemThemeWatcherAttached) return
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return
  }
  systemThemeWatcherAttached = true
  window
    .matchMedia('(prefers-color-scheme: dark)')
    .addEventListener('change', () => {
      const { settings } = useAppSettings.getState()
      if (settings.themeMode === 'system') applySideEffects(settings)
    })
}

// ---- 便捷 selector（组件用） ----

export function selectSettings(s: AppSettingsState): AppSettings {
  return s.settings
}

/** 主题相关兼容导出：旧 store/theme.ts 的替代（Gate B 迁移后旧模块退役）。 */
export function useThemeMode(): ThemeMode {
  return useAppSettings((s) => s.settings.themeMode)
}
