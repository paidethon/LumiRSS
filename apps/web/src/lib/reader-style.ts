/** reader-style — 阅读样式纯函数库（0010a Gate F，F6/F7 共用）。
 *
 * 全部值来自 OrigRead-Desktop 源码实测（App.tsx resolveReaderBackground /
 * resolveReaderColors、shared/reader-font.ts，inspired 级独立实现）：
 * - 背景预设双主题色板（paper/mint/sepia/warm + theme 跟随）；
 * - 字体族四档 CSS 栈；
 * - WCAG 相对亮度判定（< 0.42 判深色背景 → 切浅色文字套）。
 *
 * 排版预设（F7）：内置 5 套（默认/纸感/期刊衬线/AMOLED/高对比），
 * 概念对标 TTRSS feedly 主题变体与 NetNewsWire 主题包（inspired）。 */

import type {
  ReaderBackground,
  ReaderFontFamily,
  ReaderPreset,
  UiFontStack,
} from '../store/app-settings'

// ---- 背景色板（OrigRead 双主题原值） ----

export interface ReaderPalette {
  /** 浅色主题背景 */
  light: string
  /** 深色主题背景 */
  dark: string
  /** 中文标签 */
  label: string
}

export const READER_BACKGROUNDS: Record<Exclude<ReaderBackground, 'custom'>, ReaderPalette> = {
  follow: { light: '', dark: '', label: '跟随主题' },
  paper: { light: '#fffefb', dark: '#1d1f24', label: '纸白' },
  warm: { light: '#fbf6eb', dark: '#25221d', label: '暖白' },
  sepia: { light: '#f4ecd8', dark: '#2a241b', label: '米黄' },
  mint: { light: '#eef7ee', dark: '#1d2921', label: '淡绿' },
}

/** 解析最终背景色（custom → hex；follow → null 表示跟随主题）。 */
export function resolveReaderBackground(
  bg: ReaderBackground,
  customHex: string,
  isDark: boolean,
): string | null {
  if (bg === 'follow') return null
  if (bg === 'custom') return customHex
  return isDark ? READER_BACKGROUNDS[bg].dark : READER_BACKGROUNDS[bg].light
}

// ---- 文字自适应（WCAG 亮度，OrigRead resolveReaderColors 同算法） ----

/** WCAG 相对亮度（0–1）。 */
export function relativeLuminance(hex: string): number {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return 1
  const n = parseInt(m[1], 16)
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
    const c = v / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export interface ReaderTextPalette {
  text: string
  heading: string
  muted: string
  border: string
  link: string
}

/** 深背景（亮度 < 0.42）→ 浅色文字套；否则深色文字套（OrigRead 原值）。 */
export function readerTextPalette(bgHex: string): ReaderTextPalette {
  return relativeLuminance(bgHex) < 0.42
    ? {
        text: '#d9dce4',
        heading: '#eceef4',
        muted: '#9ca1ad',
        border: 'rgba(255, 255, 255, 0.14)',
        link: '#80b8ef',
      }
    : {
        text: '#35373e',
        heading: '#24262c',
        muted: '#858791',
        border: 'rgba(58, 60, 70, 0.14)',
        link: '#584bc0',
      }
}

// ---- 字体族四档（OrigRead reader-font 栈原值） ----

export const READER_FONT_STACKS: Record<ReaderFontFamily, string> = {
  system: 'inherit',
  sans: 'ui-sans-serif, system-ui, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif',
  serif: 'ui-serif, Georgia, "Times New Roman", "Songti SC", SimSun, serif',
  mono: 'ui-monospace, SFMono-Regular, Menlo, Consolas, "LXGW WenKai Mono", monospace',
}

export const READER_FONT_LABELS: Record<ReaderFontFamily, string> = {
  system: '默认（跟随界面）',
  sans: '无衬线',
  serif: '衬线',
  mono: '等宽',
}

/** UI 字体四档（同源栈）。 */
export const UI_FONT_STACKS: Record<UiFontStack, string> = {
  default: 'var(--lumi-font-default)',
  sans: READER_FONT_STACKS.sans,
  serif: READER_FONT_STACKS.serif,
  mono: READER_FONT_STACKS.mono,
}

// ---- 段距（0017：连续 em 数值，范围见 app-settings READER_NUMERIC_RANGES） ----

// ---- 内置排版预设（F7；AC20：每套至少差异化 3 项） ----

export const BUILTIN_READER_PRESETS: ReaderPreset[] = [
  {
    id: 'default',
    name: '默认（Lumi Mist）',
    builtin: true,
    vars: {
      readerFontFamily: 'system',
      readerFontSize: 17,
      readerLineHeight: 1.85,
      readerBackground: 'follow',
      readerParagraphSpacing: 0.85,
      readerJustify: false,
    },
  },
  {
    id: 'paper-reeder',
    name: '纸感 Reeder',
    builtin: true,
    vars: {
      readerFontFamily: 'serif',
      readerFontSize: 17,
      readerLineHeight: 1.85,
      readerBackground: 'paper',
      readerParagraphSpacing: 0.85,
      readerJustify: true,
    },
  },
  {
    id: 'journal-serif',
    name: '期刊衬线',
    builtin: true,
    vars: {
      readerFontFamily: 'serif',
      readerFontSize: 19,
      readerLineHeight: 2.05,
      readerBackground: 'sepia',
      readerParagraphSpacing: 1.25,
      readerJustify: true,
    },
  },
  {
    id: 'amoled-black',
    name: 'AMOLED 真黑',
    builtin: true,
    vars: {
      readerFontFamily: 'sans',
      readerFontSize: 17,
      readerLineHeight: 1.85,
      readerBackground: 'custom',
      readerParagraphSpacing: 0.85,
      readerJustify: false,
    },
  },
  {
    id: 'high-contrast',
    name: '高对比',
    builtin: true,
    vars: {
      readerFontFamily: 'sans',
      readerFontSize: 21,
      readerLineHeight: 1.85,
      readerBackground: 'custom',
      readerParagraphSpacing: 0.85,
      readerJustify: false,
    },
  },
]

/** AMOLED / 高对比两套预设的 custom 背景 hex（自定义背景值挂预设外）。 */
export const PRESET_CUSTOM_BACKGROUNDS: Record<string, string> = {
  'amoled-black': '#000000',
  'high-contrast': '#ffffff',
}

// ---- 自定义 CSS 前缀（F7，AC14：仅作用于正文） ----

/** 给普通选择器加 .lumi-reader 前缀；@media/@supports 块递归；
 * 解析失败返回 null（调用方整段拒绝）。
 * 简易实现：按块解析（花括号配对），不完整 CSS parser——足够覆盖
 * 用户手写的「选择器 { 属性 }」语法；复杂嵌套一律拒绝（安全侧）。 */
export function prefixCustomCss(css: string, prefix = '.lumi-reader'): string | null {
  try {
    return prefixBlock(css, prefix)
  } catch {
    return null
  }
}

/** 找配对的 close（跳过嵌套块）：从 open（含）起找深度归零的 }。 */
function matchingClose(css: string, open: number): number {
  let depth = 0
  for (let i = open; i < css.length; i++) {
    if (css[i] === '{') depth++
    else if (css[i] === '}') {
      depth--
      if (depth === 0) return i
    }
  }
  return -1
}

function prefixBlock(css: string, prefix: string): string {
  let out = ''
  let i = 0
  while (i < css.length) {
    const open = css.indexOf('{', i)
    if (open === -1) {
      out += css.slice(i)
      return out
    }
    const head = css.slice(i, open)
    const close = matchingClose(css, open)
    if (close === -1) throw new Error('unbalanced')
    const body = css.slice(open + 1, close)

    if (head.trim().startsWith('@')) {
      // at-rule：@media/@supports 递归 body；@keyframes 原样保留
      // （percent 选择器不能加前缀）
      if (/^@(media|supports|layer|container)\b/i.test(head.trim())) {
        out += `${head.trim()}{${prefixBlock(body, prefix)}}`
      } else {
        out += `${head.trim()}{${body}}`
      }
    } else {
      // 普通选择器列表：每个加前缀；本身已带前缀/已是 :root 的不加
      const selectors = head
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
        .map((s) => {
          if (s === 'from' || s === 'to' || /^(\d+%|:root|html|body)$/.test(s)) return s
          if (s.startsWith(prefix) || s.includes(' ' + prefix)) return s
          return `${prefix} ${s}`
        })
      if (selectors.length === 0) throw new Error('empty selector')
      out += `${selectors.join(', ')}{${body}}`
    }
    i = close + 1
  }
  return out
}
