/** theme-pack — Lumi Reader Theme Pack（0012 Gate 6）。
 *
 * .lumitheme 本质为 JSON：
 * ```json
 * {
 *   "schemaVersion": 1,
 *   "appName": "LumiRSS",
 *   "type": "reader-theme",
 *   "metadata": { "name": "", "description": "", "author": "", "createdAt": "" },
 *   "reader": { ...reader 设置字段子集 },
 *   "customCss": ""
 * }
 * ```
 *
 * 导入流程（Spec 冻结）：parse → schema validate → normalize → preview
 * → 用户确认 → apply。本模块提供前四步的纯函数；确认与 apply 由 UI 层
 * 编排（settings.update patch）。
 *
 * 安全规则（AC10）：
 * - 主题包不包含 secret/cookie/localStorage dump/字体二进制/任意 JS/HTML；
 *   本模块从结构上只接受 reader 白名单字段 + 短文本 metadata + 有限长度
 *   customCss（走与手工 CSS 相同的 .lumi-reader prefix 流程）；
 * - 所有字符串字段长度截断；未知字段丢弃（复用 normalizeSettings）；
 * - export 永不导出非 reader 字段（accent/UI 布局/翻译配置等）。
 *
 * 兼容（AC11）：0010a 旧 reader-presets JSON 继续可导入（取首个预设
 * 的 vars 作为 reader 段）；现有预设导入导出功能不受影响。 */

import {
  type AppSettings,
  normalizeSettings,
} from '../store/app-settings'
import { prefixCustomCss, READER_FONT_LABELS, READER_BACKGROUNDS } from './reader-style'

export const THEME_PACK_EXTENSION = '.lumitheme'
export const THEME_PACK_SCHEMA_VERSION = 1

export interface ThemePackMetadata {
  name: string
  description: string
  author: string
  createdAt: string
}

export interface LumiThemePack {
  schemaVersion: 1
  appName: 'LumiRSS'
  type: 'reader-theme'
  metadata: ThemePackMetadata
  reader: Partial<AppSettings>
  customCss: string
}

export type ThemePackErrorCode =
  | 'not-json'
  | 'bad-envelope' // 缺 schemaVersion/appName/type 或值不符
  | 'unsupported-version'
  | 'empty-reader' // reader 段无有效字段
  | 'bad-custom-css' // customCss 无法通过 prefix 校验

export class ThemePackError extends Error {
  readonly code: ThemePackErrorCode
  constructor(code: ThemePackErrorCode, message: string) {
    super(message)
    this.name = 'ThemePackError'
    this.code = code
  }
}

/** 导出时纳入主题包的 reader 字段白名单（不含任何 secret/布局/账号）。 */
const READER_FIELDS = [
  'readerFontFamily',
  'readerFontSize',
  'readerLineHeight',
  'readerContentWidth',
  'readerBackground',
  'readerBackgroundCustom',
  'readerParagraphSpacing',
  'readerJustify',
  'readerImageMode',
  'readerTextIndent',
  'readerHangingPunctuation',
  'readerChineseConversion',
  'readerCodeHighlight',
  'readerCodeTheme',
  'readerCustomFontId',
] as const satisfies readonly (keyof AppSettings)[]

// ---- 导出 ----

/** 从当前设置导出主题包（export → import → export 语义 round-trip）。 */
export function exportThemePack(
  settings: AppSettings,
  metadata: Partial<ThemePackMetadata> = {},
): LumiThemePack {
  const reader: Partial<AppSettings> = {}
  for (const key of READER_FIELDS) {
    ;(reader as Record<string, unknown>)[key] = settings[key]
  }
  return {
    schemaVersion: THEME_PACK_SCHEMA_VERSION,
    appName: 'LumiRSS',
    type: 'reader-theme',
    metadata: {
      name: clampStr(metadata.name ?? '我的阅读主题', 64),
      description: clampStr(metadata.description ?? '', 280),
      author: clampStr(metadata.author ?? '', 64),
      createdAt: new Date().toISOString(),
    },
    reader,
    customCss: settings.customCss,
  }
}

/** 序列化为下载文件内容。 */
export function serializeThemePack(pack: LumiThemePack): string {
  return JSON.stringify(pack, null, 2)
}

/** 触发浏览器下载 .lumitheme 文件。 */
export function downloadThemePack(pack: LumiThemePack): void {
  const blob = new Blob([serializeThemePack(pack)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  const safeName = pack.metadata.name.replace(/[^\w\u4e00-\u9fff-]+/g, '_').slice(0, 48) || 'theme'
  a.download = `${safeName}${THEME_PACK_EXTENSION}`
  a.click()
  URL.revokeObjectURL(url)
}

// ---- 导入（parse + validate + normalize） ----

/** 兼容旧 reader-presets JSON：取首个预设 vars 作为 reader 段。 */
function legacyPresetsToReader(data: Record<string, unknown>): Partial<AppSettings> | null {
  if (data.type !== 'reader-presets' || !Array.isArray(data.presets)) return null
  const first = data.presets.find(
    (p): p is Record<string, unknown> => typeof p === 'object' && p !== null,
  )
  if (first === undefined) return null
  const vars = (first.vars ?? {}) as Record<string, unknown>
  const reader: Partial<AppSettings> = {}
  for (const key of READER_FIELDS) {
    if (key in vars) (reader as Record<string, unknown>)[key] = vars[key]
  }
  return reader
}

/** 解析不可信的主题包 JSON。失败抛 ThemePackError（UI 显示原因）。
 * 成功返回经 normalize 的主题包（未知/非法字段已回退或丢弃）。 */
export function parseThemePack(json: string): LumiThemePack {
  let data: Record<string, unknown>
  try {
    data = JSON.parse(json) as Record<string, unknown>
  } catch {
    throw new ThemePackError('not-json', '文件不是有效的 JSON')
  }
  if (typeof data !== 'object' || data === null) {
    throw new ThemePackError('bad-envelope', '文件内容不是对象')
  }

  // 旧格式兼容（AC11）：reader-presets → 首个预设升级为主题包
  const legacyReader = legacyPresetsToReader(data)
  if (legacyReader !== null) {
    return {
      schemaVersion: 1,
      appName: 'LumiRSS',
      type: 'reader-theme',
      metadata: {
        name: '导入的旧版预设',
        description: '由 0010a reader-presets 预设转换而来',
        author: '',
        createdAt: new Date().toISOString(),
      },
      reader: legacyReader,
      customCss: '',
    }
  }

  if (data.type !== 'reader-theme' || data.appName !== 'LumiRSS') {
    throw new ThemePackError('bad-envelope', '不是有效的 LumiRSS 阅读主题包')
  }
  if (data.schemaVersion !== 1) {
    throw new ThemePackError(
      'unsupported-version',
      `不支持的主题包版本：${String(data.schemaVersion)}`,
    )
  }

  const rawReader = (data.reader ?? {}) as Record<string, unknown>
  const picked: Record<string, unknown> = {}
  let hasField = false
  for (const key of READER_FIELDS) {
    if (key in rawReader) {
      picked[key] = rawReader[key]
      hasField = true
    }
  }
  if (!hasField) {
    throw new ThemePackError('empty-reader', '主题包不包含任何阅读设置')
  }

  const customCss = typeof data.customCss === 'string' ? data.customCss.slice(0, 64_000) : ''
  if (customCss.trim() !== '' && prefixCustomCss(customCss) === null) {
    throw new ThemePackError(
      'bad-custom-css',
      '主题包中的自定义 CSS 无法解析（花括号不配对或空选择器）',
    )
  }

  const m = (data.metadata ?? {}) as Record<string, unknown>
  // normalize：非法 reader 字段值回退当前默认（normalizeSettings 合并语义）
  const normalized = normalizeSettings(picked)
  const reader: Partial<AppSettings> = {}
  for (const key of READER_FIELDS) {
    ;(reader as Record<string, unknown>)[key] = normalized[key]
  }

  return {
    schemaVersion: 1,
    appName: 'LumiRSS',
    type: 'reader-theme',
    metadata: {
      name: clampStr(m.name, 64) || '未命名主题',
      description: clampStr(m.description, 280),
      author: clampStr(m.author, 64),
      createdAt: typeof m.createdAt === 'string' ? clampStr(m.createdAt, 40) : '',
    },
    reader,
    customCss,
  }
}

// ---- 应用 ----

/** 把主题包变成 settings.update 的 patch（UI 用户确认后调用）。
 * customCss 覆盖当前值（经 prefix 校验，渲染时同样走 .lumi-reader 前缀）。 */
export function themePackToPatch(pack: LumiThemePack): Partial<AppSettings> {
  return { ...pack.reader, customCss: pack.customCss }
}

// ---- Preview ----

export interface ThemePackPreview {
  name: string
  description: string
  author: string
  fontFamilyLabel: string
  fontSize: number
  lineHeight: number
  backgroundLabel: string
  hasCustomCss: boolean
  chineseConversion: string
  textIndent: string
  /** 主题包引用了本机不存在的自定义字体（仅本地导入场景检测） */
  missingFont: boolean
}

/** 生成 preview 摘要（Spec：名称/描述/字体/背景/字号/行高/中文排版/
 * 是否含 custom CSS）。missingFontFont 检测由 UI 传入 hasFont 回调。 */
export function previewThemePack(
  pack: LumiThemePack,
  hasLocalFont: (id: string) => boolean = () => false,
): ThemePackPreview {
  const r = pack.reader
  const fontId = r.readerCustomFontId ?? null
  const bg = r.readerBackground ?? 'follow'
  return {
    name: pack.metadata.name,
    description: pack.metadata.description,
    author: pack.metadata.author,
    fontFamilyLabel: fontId !== null
      ? hasLocalFont(fontId)
        ? '自定义字体'
        : '自定义字体（本机缺少，将回退）'
      : READER_FONT_LABELS[r.readerFontFamily ?? 'system'],
    fontSize: r.readerFontSize ?? 17,
    lineHeight: r.readerLineHeight ?? 1.85,
    backgroundLabel:
      bg === 'custom' ? `自定义 ${r.readerBackgroundCustom ?? ''}` : READER_BACKGROUNDS[bg as Exclude<typeof bg, 'custom'>].label,
    hasCustomCss: pack.customCss.trim() !== '',
    chineseConversion: CHINESE_CONVERSION_LABELS[r.readerChineseConversion ?? 'off'],
    textIndent: r.readerTextIndent === '2em' ? '首行缩进 2 字符' : '无首行缩进',
    missingFont: fontId !== null && !hasLocalFont(fontId),
  }
}

const CHINESE_CONVERSION_LABELS: Record<string, string> = {
  off: '原文',
  s2t: '简 → 繁',
  t2s: '繁 → 简',
  tw: '简 → 台湾正体',
  hk: '简 → 香港繁体',
}

function clampStr(value: unknown, max: number): string {
  return typeof value === 'string' ? value.slice(0, max) : ''
}
