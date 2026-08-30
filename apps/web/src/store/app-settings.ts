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
  READER_PARAGRAPH_SPACING_EM,
  resolveReaderBackground,
  readerTextPalette,
  prefixCustomCss,
} from '../lib/reader-style'

export const SETTINGS_STORAGE_KEY = 'lumirss-settings'

// ---- 类型化模型（Spec §设计规格 + 0010a Gate F 扩展） ----

export type ReaderFontSize = 15 | 17 | 19 | 21
export type ReaderLineHeight = 1.65 | 1.85 | 2.05
export type ReaderContentWidth = 680 | 760 | 900
/** 0010a F6：背景扩展（+paper/mint/custom，OrigRead 双主题色板原值） */
export type ReaderBackground = 'follow' | 'sepia' | 'warm' | 'paper' | 'mint' | 'custom'
/** 字体族四档（OrigRead reader-font 栈原值，inspired） */
export type ReaderFontFamily = 'system' | 'sans' | 'serif' | 'mono'
export type ReaderParagraphSpacing = 'compact' | 'normal' | 'loose'
export type ReaderImageMode = 'all' | 'grayscale' | 'hidden'
/** UI 字体四档（同源 OrigRead 栈） */
export type UiFontStack = 'default' | 'sans' | 'serif' | 'mono'
export type UiFontSize = 15 | 16 | 18 | 20

/** 翻译 Provider（OrigRead translation.ts 镜像，裁剪 MLKit/Google） */
export type TranslationProviderType = 'microsoft' | 'deepl' | 'dlx'
export interface TranslationProvider {
  type: TranslationProviderType
  enabled: boolean
  endpoint: string
  region: string
  apiKey: string
}
export interface TranslationSettings {
  defaultProvider: TranslationProviderType
  targetLanguage: string
  displayMode: 'translated' | 'bilingual'
  providers: TranslationProvider[]
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

/** RSSHub 实例（OrigRead rsshub.ts 镜像，16 内置清单） */
export interface RssHubInstance {
  id: string
  url: string
  location: string
  maintainer: string
  enabled: boolean
  builtIn: boolean
}
export interface RssHubSettings {
  enabled: boolean
  instances: RssHubInstance[]
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
  language: 'zh-CN' // 'en' planned（枚举占位，值只有 zh-CN）
  sidebarHideRead: boolean
  timelineUnreadDot: boolean
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
  /** OrigRead 四页（0010a F2–F5） */
  translationSettings: TranslationSettings
  filterRules: FilterRule[]
  filterStats: FilterStats
  rsshubSettings: RssHubSettings
  /** 原有阅读/布局 */
  themeMode: ThemeMode
  readerFontSize: ReaderFontSize
  readerLineHeight: ReaderLineHeight
  readerContentWidth: ReaderContentWidth
  /** 布局（<1024 忽略；Gate C 接线） */
  sidebarWidth: number // clamp 220–300
  sidebarCollapsed: boolean
  timelineWidth: number // clamp 360–460
  timelineCollapsed: boolean
}

// ---- 内置翻译 Provider 默认（OrigRead 预设 endpoint 原值） ----

export const TRANSLATION_PROVIDER_DEFAULTS: Record<
  TranslationProviderType,
  { endpoint: string; region: string; label: string }
> = {
  microsoft: {
    endpoint: 'https://api.cognitive.microsofttranslator.com',
    region: '',
    label: 'Microsoft Translator',
  },
  deepl: {
    endpoint: 'https://api-free.deepl.com/v2/translate',
    region: '',
    label: 'DeepL（免费版）',
  },
  dlx: { endpoint: '', region: '', label: 'DeepLX（自建）' },
}

// ---- RSSHub 16 内置实例（OrigRead 两端逐字一致清单） ----

export const BUILTIN_RSSHUB_INSTANCES: RssHubInstance[] = [
  { id: 'official', url: 'https://rsshub.app', location: 'US', maintainer: 'DIYgod', enabled: true, builtIn: true },
  { id: 'rssforever', url: 'https://rsshub.rssforever.com', location: 'CN', maintainer: 'rssforever', enabled: true, builtIn: true },
  { id: 'slarker', url: 'https://rsshub.slarker.me', location: 'US', maintainer: 'slarker', enabled: true, builtIn: true },
  { id: 'pseudoyu', url: 'https://rsshub.pseudoyu.com', location: 'GLOBAL', maintainer: 'pseudoyu', enabled: true, builtIn: true },
  { id: 'rsstips', url: 'https://rsshub.rsstips.com', location: 'HK', maintainer: 'rsstips', enabled: true, builtIn: true },
  { id: 'ktachibana', url: 'https://rsshub.ktachibana.party', location: 'GB', maintainer: 'ktachibana', enabled: true, builtIn: true },
  { id: 'owonz', url: 'https://rsshub.owonz.com', location: 'CN', maintainer: 'owonz', enabled: true, builtIn: true },
  { id: 'wudifeixue', url: 'https://rsshub.wudifeixue.com', location: 'CN', maintainer: 'wudifeixue', enabled: true, builtIn: true },
  { id: 'henry', url: 'https://rsshub.henry.wang', location: 'AE', maintainer: 'HenryQW', enabled: true, builtIn: true },
  { id: 'umzzz', url: 'https://rsshub.umzzz.com', location: 'CN', maintainer: 'umzzz', enabled: true, builtIn: true },
  { id: 'isrss', url: 'https://rsshub.isrss.com', location: 'GLOBAL', maintainer: 'isrss', enabled: true, builtIn: true },
  { id: 'emailonce', url: 'https://rsshub.emailonce.com', location: 'GLOBAL', maintainer: 'emailonce', enabled: true, builtIn: true },
  { id: 'datuan', url: 'https://rsshub.datuan.dev', location: 'US', maintainer: 'datuan', enabled: true, builtIn: true },
  { id: 'cups', url: 'https://rsshub.cups.work', location: 'GLOBAL', maintainer: 'cups', enabled: true, builtIn: true },
  { id: 'spriple', url: 'https://rsshub.spriple.xyz', location: 'GLOBAL', maintainer: 'spriple', enabled: true, builtIn: true },
  { id: 'virworks', url: 'https://rsshub.virworks.com', location: 'GLOBAL', maintainer: 'virworks', enabled: true, builtIn: true },
]

export const DEFAULT_APP_SETTINGS: AppSettings = {
  language: 'zh-CN',
  sidebarHideRead: false,
  timelineUnreadDot: true,
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
  readerParagraphSpacing: 'normal',
  readerJustify: false,
  readerImageMode: 'all',
  readerPresetId: 'default',
  readerPresets: [],
  translationSettings: {
    defaultProvider: 'microsoft',
    targetLanguage: 'zh-CN',
    displayMode: 'translated',
    providers: (['microsoft', 'deepl', 'dlx'] as const).map((type) => ({
      type,
      enabled: type === 'microsoft',
      endpoint: TRANSLATION_PROVIDER_DEFAULTS[type].endpoint,
      region: '',
      apiKey: '',
    })),
  },
  filterRules: [],
  filterStats: { totalFiltered: 0, lastFilteredAt: null, lastMatchedRule: null },
  rsshubSettings: { enabled: true, instances: BUILTIN_RSSHUB_INSTANCES },
  themeMode: 'system',
  readerFontSize: 17,
  readerLineHeight: 1.85,
  readerContentWidth: 760,
  sidebarWidth: 240,
  sidebarCollapsed: false,
  timelineWidth: 400,
  timelineCollapsed: false,
}

// ---- 解析 / 迁移（纯函数，可测试） ----

const READER_BG_VALUES = ['follow', 'sepia', 'warm', 'paper', 'mint', 'custom'] as const
const FONT_SIZES = [15, 17, 19, 21] as const
const LINE_HEIGHTS = [1.65, 1.85, 2.05] as const
const CONTENT_WIDTHS = [680, 760, 900] as const
const READER_FONT_FAMILIES = ['system', 'sans', 'serif', 'mono'] as const
const PARAGRAPH_SPACINGS = ['compact', 'normal', 'loose'] as const
const IMAGE_MODES = ['all', 'grayscale', 'hidden'] as const
const UI_FONT_STACK_VALUES = ['default', 'sans', 'serif', 'mono'] as const
const UI_FONT_SIZES = [15, 16, 18, 20] as const
const TRANSLATION_PROVIDER_TYPES = ['microsoft', 'deepl', 'dlx'] as const

const HEX_COLOR_RE = /^#[0-9a-f]{6}$/i

function pickHexColor(value: unknown, fallback: string): string {
  return typeof value === 'string' && HEX_COLOR_RE.test(value.trim())
    ? value.trim().toLowerCase()
    : fallback
}

function pickString<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback
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

function normalizeTranslation(raw: unknown): TranslationSettings {
  const def = DEFAULT_APP_SETTINGS.translationSettings
  if (typeof raw !== 'object' || raw === null) return structuredClone(def)
  const t = raw as Record<string, unknown>
  const providers: TranslationProvider[] = []
  const seenTypes = new Set<string>()
  if (Array.isArray(t.providers)) {
    for (const p of t.providers) {
      if (typeof p !== 'object' || p === null) continue
      const pr = p as Record<string, unknown>
      const type = TRANSLATION_PROVIDER_TYPES.find((x) => x === pr.type)
      if (!type || seenTypes.has(type)) continue
      seenTypes.add(type)
      providers.push({
        type,
        enabled: typeof pr.enabled === 'boolean' ? pr.enabled : type === 'microsoft',
        endpoint: typeof pr.endpoint === 'string' ? pr.endpoint : '',
        region: typeof pr.region === 'string' ? pr.region : '',
        apiKey: typeof pr.apiKey === 'string' ? pr.apiKey : '',
      })
    }
  }
  // 至少保留 1 个启用 Provider（OrigRead 交互不变量）
  const completed = providers.length > 0 ? providers : structuredClone(def.providers)
  if (!completed.some((p) => p.enabled)) completed[0].enabled = true
  const defaultProvider = TRANSLATION_PROVIDER_TYPES.includes(
    t.defaultProvider as TranslationProviderType,
  )
    ? (t.defaultProvider as TranslationProviderType)
    : def.defaultProvider
  return {
    defaultProvider: completed.some((p) => p.type === defaultProvider)
      ? defaultProvider
      : completed[0].type,
    targetLanguage:
      typeof t.targetLanguage === 'string' && t.targetLanguage.trim()
        ? t.targetLanguage.trim().slice(0, 16)
        : def.targetLanguage,
    displayMode: t.displayMode === 'bilingual' ? 'bilingual' : 'translated',
    providers: completed,
  }
}

function normalizeRssHub(raw: unknown): RssHubSettings {
  const def = DEFAULT_APP_SETTINGS.rsshubSettings
  if (typeof raw !== 'object' || raw === null)
    return { enabled: def.enabled, instances: structuredClone(def.instances) }
  const r = raw as Record<string, unknown>
  const instances: RssHubInstance[] = Array.isArray(r.instances)
    ? r.instances
        .filter((i): i is Record<string, unknown> => typeof i === 'object' && i !== null)
        .map((i, idx) => ({
          id: typeof i.id === 'string' && i.id ? i.id : `custom-${idx}`,
          url: typeof i.url === 'string' ? i.url.trim() : '',
          location: typeof i.location === 'string' ? i.location : 'GLOBAL',
          maintainer: typeof i.maintainer === 'string' ? i.maintainer : '',
          enabled: typeof i.enabled === 'boolean' ? i.enabled : true,
          builtIn: i.builtIn === true,
        }))
        .filter((i) => i.url.length > 0)
    : structuredClone(def.instances)
  return {
    enabled: typeof r.enabled === 'boolean' ? r.enabled : def.enabled,
    instances: instances.length > 0 ? instances : structuredClone(def.instances),
  }
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
        readerFontSize: pickNumber(v.readerFontSize, FONT_SIZES, 17),
        readerLineHeight: pickNumber(v.readerLineHeight, LINE_HEIGHTS, 1.85),
        readerBackground: pickString(v.readerBackground, READER_BG_VALUES, 'follow'),
        readerParagraphSpacing: pickString(v.readerParagraphSpacing, PARAGRAPH_SPACINGS, 'normal'),
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
    sidebarHideRead:
      typeof source.sidebarHideRead === 'boolean'
        ? source.sidebarHideRead
        : DEFAULT_APP_SETTINGS.sidebarHideRead,
    timelineUnreadDot:
      typeof source.timelineUnreadDot === 'boolean'
        ? source.timelineUnreadDot
        : DEFAULT_APP_SETTINGS.timelineUnreadDot,
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
    readerParagraphSpacing: pickString(
      source.readerParagraphSpacing,
      PARAGRAPH_SPACINGS,
      DEFAULT_APP_SETTINGS.readerParagraphSpacing,
    ),
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
    translationSettings: normalizeTranslation(source.translationSettings),
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
    rsshubSettings: normalizeRssHub(source.rsshubSettings),
    themeMode: isThemeMode(source.themeMode)
      ? source.themeMode
      : DEFAULT_APP_SETTINGS.themeMode,
    readerFontSize: pickNumber(source.readerFontSize, FONT_SIZES, DEFAULT_APP_SETTINGS.readerFontSize),
    readerLineHeight: pickNumber(
      source.readerLineHeight,
      LINE_HEIGHTS,
      DEFAULT_APP_SETTINGS.readerLineHeight,
    ),
    readerContentWidth: pickNumber(
      source.readerContentWidth,
      CONTENT_WIDTHS,
      DEFAULT_APP_SETTINGS.readerContentWidth,
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

  // 0010a F6：字体族 / 段距 / 对齐
  root.style.setProperty('--lumi-reader-font-family', READER_FONT_STACKS[settings.readerFontFamily])
  root.style.setProperty('--lumi-reader-paragraph-spacing', READER_PARAGRAPH_SPACING_EM[settings.readerParagraphSpacing])
  root.style.setProperty('--lumi-reader-text-align', settings.readerJustify ? 'justify' : 'start')
  // 图片模式：灰度/隐藏由 .article-content img 消费
  root.dataset.readerImages = settings.readerImageMode

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

interface AppSettingsState {
  settings: AppSettings
  /** 局部更新（借鉴 OrigRead Patch 模式）：合并 + 归一化 + 持久化 +
   *  副作用（主题/排版 CSS 变量同步）。 */
  update: (patch: Partial<AppSettings>) => void
  /** 重置为默认（数据控制页「恢复默认设置」用）。 */
  reset: () => void
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
}))

/** 启动路径（main.tsx 调一次）：加载并把副作用应用到 DOM。 */
export function initAppSettings(): void {
  applySideEffects(useAppSettings.getState().settings)
}

// ---- 便捷 selector（组件用） ----

export function selectSettings(s: AppSettingsState): AppSettings {
  return s.settings
}

/** 主题相关兼容导出：旧 store/theme.ts 的替代（Gate B 迁移后旧模块退役）。 */
export function useThemeMode(): ThemeMode {
  return useAppSettings((s) => s.settings.themeMode)
}
