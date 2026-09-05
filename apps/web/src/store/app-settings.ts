/** 应用设置 store — 0010 Gate A。
 *
 * 类型化客户端设置（借鉴 OrigRead-Desktop DesktopSettings 模式，inspired）：
 * 单一 interface + zustand + localStorage 单 key（lumirss-settings）持久化。
 *
 * 迁移（AC17/V11）：旧 key lumirss-theme / lumirss-reader-bg 的数据在
 * 首次读取时并入（旧 key 保留不删——兼容一个版本，0017 服务端设置
 * 落地时统一收口）。themeMode/readerBackground 迁入后，旧 store
 * （store/theme.ts、lib/reader-bg.ts）改为本 store 的薄封装（Gate A
 * 先并存，Gate B 完成接线后旧模块退役）。
 *
 * Reader 排版（fontSize/lineHeight/contentWidth）由本 store 挂 CSS 变量
 * 到 <html>（--lumi-reader-font-size 等，Gate B 接线）。 */

import { create } from 'zustand'
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

export const SETTINGS_STORAGE_KEY = 'lumirss-settings'

// ---- 0017：连续数值范围（AD-0017-1，min/default/max/step 唯一来源） ----

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

export const READER_NUMERIC_RANGES: Record<ReaderNumericKey, NumericRange> = {
  readerFontSize: { min: 12, max: 28, step: 1, default: 17 },
  readerLineHeight: { min: 1.2, max: 2.4, step: 0.05, default: 1.85 },
  readerParagraphSpacing: { min: 0, max: 2.0, step: 0.05, default: 0.85 },
  readerContentWidth: { min: 560, max: 1080, step: 20, default: 760 },
  readerPageMargin: { min: 12, max: 64, step: 4, default: 32 },
}

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
/** 代码高亮：自动（含 code 文章按需加载 Shiki）/ 关闭 */
export type ReaderCodeHighlight = 'auto' | 'off'

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
  /** 阅读时间估算开关（ReaderHeader 弱化显示） */
  readerShowReadingTime: boolean
  /** 代码高亮 + 主题 */
  readerCodeHighlight: ReaderCodeHighlight
  readerCodeTheme: string
  /** 实验性：词首强调（Bionic-style，默认关） */
  readerBionic: boolean
  /** 布局（<1024 忽略；Gate C 接线） */
  sidebarWidth: number // clamp 220–300
  sidebarCollapsed: boolean
  timelineWidth: number // clamp 360–460
  timelineCollapsed: boolean
}

export const DEFAULT_APP_SETTINGS: AppSettings = {
  language: 'zh-CN',
  dimRead: false,
  groupByDate: false,
  unreadOnly: false,
  scrollMarkUnread: false,
  accentColor: '#6d78e8', // Lumi Mist 默认
  uiFontSize: 16,
  uiFontStack: 'default',
  reduceMotion: false,
  customCss: '',
  readerFontFamily: 'system',
  readerBackground: 'follow',
  readerBackgroundCustom: '#eef7ee',
  readerParagraphSpacing: 0.85,
  readerJustify: false,
  readerImageMode: 'all',
  readerPresetId: 'default',
  readerPresets: [],
  filterRules: [],
  filterStats: { totalFiltered: 0, lastFilteredAt: null, lastMatchedRule: null },
  themeMode: 'system',
  readerFontSize: 17,
  readerLineHeight: 1.85,
  readerContentWidth: 760,
  readerPageMargin: 32,
  readerCustomFontId: null,
  readerFontUrl: null,
  readerFontUrlName: '',
  readerTextIndent: 'off',
  readerHangingPunctuation: false,
  readerChineseConversion: 'off',
  readerShowReadingTime: false,
  readerCodeHighlight: 'auto',
  readerCodeTheme: 'auto',
  readerBionic: false,
  sidebarWidth: 240,
  sidebarCollapsed: false,
  timelineWidth: 400,
  timelineCollapsed: false,
}

// ---- 解析 / 迁移（纯函数，可测试） ----

const READER_BG_VALUES = ['follow', 'sepia', 'warm', 'paper', 'mint', 'custom'] as const
const READER_FONT_FAMILIES = ['system', 'sans', 'serif', 'mono'] as const
const IMAGE_MODES = ['all', 'grayscale', 'hidden'] as const
const UI_FONT_STACK_VALUES = ['default', 'sans', 'serif', 'mono'] as const
const UI_FONT_SIZES = [15, 16, 18, 20] as const
// 0012 新增枚举表
const READER_TEXT_INDENTS = ['off', '2em'] as const
const READER_CHINESE_CONVERSIONS = ['off', 's2t', 't2s', 'tw', 'hk'] as const
const READER_CODE_HIGHLIGHTS = ['auto', 'off'] as const
/** Shiki 主题白名单（auto = 随 Reader 明暗切换；其余为单主题锁定） */
const READER_CODE_THEMES = ['auto', 'github-light', 'github-dark', 'vitesse-light', 'vitesse-dark'] as const

const HEX_COLOR_RE = /^#[0-9a-f]{6}$/i

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
  for (const item of raw) {
    if (typeof item !== 'object' || item === null) continue
    const p = item as Record<string, unknown>
    const v = (p.vars ?? {}) as Record<string, unknown>
    const id = typeof p.id === 'string' && p.id && !ids.has(p.id) ? p.id : null
    const name = typeof p.name === 'string' && p.name.trim() ? p.name.trim().slice(0, 32) : null
    if (!id || !name) continue
    ids.add(id)
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
  }
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, Math.round(value)))
}

/** 首次加载：读新 key；不存在则从旧 key（theme/reader-bg）迁移。 */
export function loadSettings(storage: Storage | null): AppSettings {
  if (storage === null) return { ...DEFAULT_APP_SETTINGS }
  try {
    const raw = storage.getItem(SETTINGS_STORAGE_KEY)
    if (raw !== null) {
      return normalizeSettings(JSON.parse(raw))
    }
    // 迁移路径：旧 key 数据并入默认值
    const migrated = { ...DEFAULT_APP_SETTINGS }
    const oldTheme = storage.getItem('lumirss-theme')
    if (isThemeMode(oldTheme)) migrated.themeMode = oldTheme
    const oldReaderBg = storage.getItem('lumirss-reader-bg')
    if (READER_BG_VALUES.includes(oldReaderBg as ReaderBackground)) {
      migrated.readerBackground = oldReaderBg as ReaderBackground
    }
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

/** Reader 排版 CSS 变量挂载（Gate B 由 Reader 消费；此处为挂载逻辑）。 */
export function applyReaderTypography(settings: AppSettings): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.style.setProperty('--lumi-reader-font-size', `${settings.readerFontSize}px`)
  root.style.setProperty('--lumi-reader-line-height', String(settings.readerLineHeight))
  root.style.setProperty('--lumi-reader-content-width', `${settings.readerContentWidth}px`)

  // 0010a F6：字体族 / 段距 / 对齐；0012：自定义字体优先于档位栈
  //（字体未注册完成时 CSS 自动回退档位栈，不白屏）
  let customFamily: string | null = null
  if (settings.readerCustomFontId !== null) {
    customFamily = fontFamilyName(settings.readerCustomFontId)
  } else if (settings.readerFontUrl !== null) {
    customFamily = fontFamilyName(fontIdFromUrl(settings.readerFontUrl))
  }
  const baseStack = READER_FONT_STACKS[settings.readerFontFamily]
  root.style.setProperty(
    '--lumi-reader-font-family',
    customFamily !== null ? `"${customFamily}", ${baseStack}` : baseStack,
  )
  // 0017：段距是连续 em 数值；页面边距是连续 px 数值（移动端 CSS 钳制）
  root.style.setProperty('--lumi-reader-paragraph-spacing', `${settings.readerParagraphSpacing}em`)
  root.style.setProperty('--lumi-reader-page-margin', `${settings.readerPageMargin}px`)
  root.style.setProperty('--lumi-reader-text-align', settings.readerJustify ? 'justify' : 'start')
  // 图片模式：灰度/隐藏由 .article-content img 消费
  root.dataset.readerImages = settings.readerImageMode

  // 0012 Gate 4：中文排版（首行缩进相对单位；标点悬挂 progressive
  // enhancement —— CSS 侧用 @supports 包裹，这里只挂变量/标记）
  root.style.setProperty('--lumi-reader-text-indent', settings.readerTextIndent === '2em' ? '2em' : '0')
  root.dataset.readerHangingPunctuation = settings.readerHangingPunctuation ? 'true' : 'false'
  // 简繁转换标记（展示层 transform 的开关，ArticleContent 消费）
  root.dataset.readerChineseConversion = settings.readerChineseConversion

  // 预设驱动的 custom 背景（AMOLED/高对比等内置预设携带的背景）
  const customBg =
    settings.readerPresetId in PRESET_CUSTOM_BACKGROUNDS
      ? PRESET_CUSTOM_BACKGROUNDS[settings.readerPresetId]
      : settings.readerBackgroundCustom
  const isDark = resolveTheme(settings.themeMode, prefersDarkScheme()) === 'dark'
  const bgHex = resolveReaderBackground(settings.readerBackground, customBg, isDark)
  if (bgHex === null) {
    root.style.removeProperty('--lumi-reader-bg')
    root.style.removeProperty('--lumi-reader-text')
    root.style.removeProperty('--lumi-reader-heading')
    root.style.removeProperty('--lumi-reader-muted')
    root.style.removeProperty('--lumi-reader-border')
    root.style.removeProperty('--lumi-reader-link')
  } else {
    const palette = readerTextPalette(bgHex)
    root.style.setProperty('--lumi-reader-bg', bgHex)
    root.style.setProperty('--lumi-reader-text', palette.text)
    root.style.setProperty('--lumi-reader-heading', palette.heading)
    root.style.setProperty('--lumi-reader-muted', palette.muted)
    root.style.setProperty('--lumi-reader-border', palette.border)
    root.style.setProperty('--lumi-reader-link', palette.link)
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
 * 这些键参与 /api/v1/settings 同步；其余设置是设备本地状态。 */
export const PORTABLE_KEYS = [
  'themeMode',
  'accentColor',
  'uiFontStack',
  'uiFontSize',
  'reduceMotion',
  'readerFontFamily',
  'readerFontSize',
  'readerLineHeight',
  'readerParagraphSpacing',
  'readerContentWidth',
  'readerPageMargin',
  'readerBackground',
  'readerBackgroundCustom',
  'readerJustify',
  'readerImageMode',
  'readerTextIndent',
  'readerHangingPunctuation',
  'readerChineseConversion',
  'readerShowReadingTime',
  'readerCodeHighlight',
  'readerCodeTheme',
  'scrollMarkUnread',
] as const

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
  'readerJustify',
  'readerImageMode',
  'readerTextIndent',
  'readerHangingPunctuation',
  'readerChineseConversion',
  'readerShowReadingTime',
  'readerCodeHighlight',
  'readerCodeTheme',
  'readerBionic',
  'scrollMarkUnread',
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
