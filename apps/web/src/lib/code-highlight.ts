/** code-highlight — Shiki lazy 代码高亮（0012 Gate 8）。
 *
 * Bundle 纪律（Spec：按需加载 > 巨型 bundle）：
 * - 只有「文章含 <pre><code> 且设置为 auto」才会 dynamic import shiki；
 * - fine-grained：`shiki/core` + JS regex engine（无 wasm），语言/主题
 *   各自独立 chunk，仅加载用到的；
 * - 未识别语言 → 保留 plaintext 原样（不加载对应语言包）。
 *
 * 安全（与 sanitize 策略协同）：
 * - 我们的应用 sanitize 策略 FORBID_ATTR style（禁止 inline style）。
 *   Shiki 默认输出 inline color —— 因此这里用 codeToTokens + DOM API
 *   自建 span：token 颜色（来自我们打包的主题，非文章内容）映射为
 *   确定性 class（.lumi-sh-<hex>），并维护一个 document.head 里的
 *   颜色 class 样式表（内容只来自 bundled 主题色板）。
 * - 输出的 span 全部 createElement/textContent 构建，最终仍过
 *   DOMPurify（在 article-pipeline 的终点）。 */

import type { HighlighterCore } from 'shiki/core'

// ---- 语言白名单（lazy import 映射） ----

const LANG_IMPORTS: Record<string, () => Promise<unknown>> = {
  javascript: () => import('shiki/langs/javascript.mjs'),
  typescript: () => import('shiki/langs/typescript.mjs'),
  json: () => import('shiki/langs/json.mjs'),
  html: () => import('shiki/langs/html.mjs'),
  css: () => import('shiki/langs/css.mjs'),
  bash: () => import('shiki/langs/bash.mjs'),
  python: () => import('shiki/langs/python.mjs'),
  java: () => import('shiki/langs/java.mjs'),
  c: () => import('shiki/langs/c.mjs'),
  cpp: () => import('shiki/langs/cpp.mjs'),
  go: () => import('shiki/langs/go.mjs'),
  rust: () => import('shiki/langs/rust.mjs'),
  markdown: () => import('shiki/langs/markdown.mjs'),
  yaml: () => import('shiki/langs/yaml.mjs'),
}

/** 常见别名 → 白名单语言。 */
const LANG_ALIASES: Record<string, string> = {
  js: 'javascript',
  jsx: 'javascript',
  mjs: 'javascript',
  cjs: 'javascript',
  ts: 'typescript',
  tsx: 'typescript',
  sh: 'bash',
  shell: 'bash',
  zsh: 'bash',
  console: 'bash',
  py: 'python',
  'c++': 'cpp',
  cxx: 'cpp',
  md: 'markdown',
  yml: 'yaml',
  xml: 'html',
  svg: 'html',
}

/** 从 code 元素的 class 里解析语言（language-x / lang-x）。 */
export function normalizeLanguage(codeEl: HTMLElement): string | null {
  const cls = codeEl.getAttribute('class') ?? ''
  const m = /(?:^|\s)(?:language|lang)-([-\w]+)(?:\s|$)/i.exec(cls)
  if (m === null) return null
  const raw = m[1].toLowerCase()
  const lang = LANG_ALIASES[raw] ?? raw
  return lang in LANG_IMPORTS ? lang : null
}

/** 快速探测：HTML 是否含 <pre><code>（决定是否值得加载 shiki）。 */
export function containsCodeBlock(html: string): boolean {
  return /<pre[^>]*>\s*<code/i.test(html)
}

// ---- 主题（白名单，与 settings READER_CODE_THEMES 对齐） ----

const THEME_IMPORTS: Record<string, () => Promise<unknown>> = {
  'github-light': () => import('shiki/themes/github-light.mjs'),
  'github-dark': () => import('shiki/themes/github-dark.mjs'),
  'vitesse-light': () => import('shiki/themes/vitesse-light.mjs'),
  'vitesse-dark': () => import('shiki/themes/vitesse-dark.mjs'),
}

export const CODE_THEMES = Object.keys(THEME_IMPORTS)

// ---- highlighter 单例（按需加载语言） ----

let highlighterPromise: Promise<HighlighterCore> | null = null
const loadedLangs = new Set<string>()
const loadedThemes = new Set<string>()

async function getHighlighter(): Promise<HighlighterCore> {
  if (highlighterPromise === null) {
    highlighterPromise = (async () => {
      const [{ createHighlighterCore }, { createJavaScriptRegexEngine }] =
        await Promise.all([import('shiki/core'), import('shiki/engine/javascript')])
      return createHighlighterCore({
        themes: [],
        langs: [],
        // JS regex 引擎：无 wasm、体积小；forgiving 容忍少数语法缺陷
        engine: createJavaScriptRegexEngine({ forgiving: true }),
      })
    })()
  }
  return highlighterPromise
}

async function ensureLang(highlighter: HighlighterCore, lang: string): Promise<void> {
  if (loadedLangs.has(lang)) return
  const mod = (await LANG_IMPORTS[lang]()) as { default: unknown }
  await highlighter.loadLanguage(mod.default as never)
  loadedLangs.add(lang)
}

async function ensureTheme(highlighter: HighlighterCore, theme: string): Promise<void> {
  if (loadedThemes.has(theme)) return
  const mod = (await THEME_IMPORTS[theme]()) as { default: unknown }
  await highlighter.loadTheme(mod.default as never)
  loadedThemes.add(theme)
}

/** 测试用：重置单例。 */
export function resetHighlighter(): void {
  highlighterPromise = null
  loadedLangs.clear()
  loadedThemes.clear()
}

// ---- 颜色 class 样式表（document.head，内容只来自 bundled 主题色板） ----

const COLOR_STYLE_ID = 'lumi-shiki-colors'
const emittedColors = new Set<string>()

function colorClass(hex: string): string {
  return `lumi-sh-${hex.replace('#', '').toLowerCase()}`
}

function ensureColorRule(hex: string): string {
  const cls = colorClass(hex)
  if (emittedColors.has(cls)) return cls
  emittedColors.add(cls)
  if (typeof document === 'undefined') return cls
  let styleEl = document.getElementById(COLOR_STYLE_ID) as HTMLStyleElement | null
  if (styleEl === null) {
    styleEl = document.createElement('style')
    styleEl.id = COLOR_STYLE_ID
    document.head.appendChild(styleEl)
  }
  // 颜色值来自 shiki bundled 主题（非文章内容），仅六位 hex 形态放行
  if (/^#[0-9a-f]{6}$/i.test(hex)) {
    styleEl.textContent += `.article-content .${cls}{color:${hex.toLowerCase()}}\n`
  }
  return cls
}

// ---- 高亮入口（inert DOM 内 transform） ----

interface ShikiToken {
  content: string
  color?: string
}

/**
 * 对 inert document.body 内的 <pre><code> 做高亮替换。
 * 返回是否至少高亮了一个块（失败/无语言 → 原样保留 plaintext）。
 * 任何异常都吞掉（graceful fallback，不让文章渲染失败）。 */
export async function highlightCodeBlocks(
  body: HTMLElement,
  themeName: string,
): Promise<boolean> {
  if (typeof DOMParser === 'undefined') return false
  const blocks = [...body.querySelectorAll('pre > code')] as HTMLElement[]
  if (blocks.length === 0) return false

  // 先解析全部语言：无任何可识别语言时不加载 shiki（plaintext 原样）
  const targets = blocks
    .map((el) => ({ el, lang: normalizeLanguage(el) }))
    .filter((t): t is { el: HTMLElement; lang: string } => t.lang !== null)
  if (targets.length === 0) return false

  const resolvedTheme = themeName in THEME_IMPORTS ? themeName : 'github-light'
  try {
    const highlighter = await getHighlighter()
    await ensureTheme(highlighter, resolvedTheme)

    let highlighted = 0
    for (const { el: codeEl, lang } of targets) {
      await ensureLang(highlighter, lang)

      const code = codeEl.textContent ?? ''
      const result = highlighter.codeToTokens(code, {
        lang,
        theme: resolvedTheme,
        includeExplanation: false,
      })
      // 构建新 <pre><code>（DOM API；token 内容 textContent 注入天然转义）
      const pre = codeEl.parentElement as HTMLElement
      const newCode = document.createElement('code')
      newCode.className = `language-${lang} lumi-shiki-code`
      for (const line of result.tokens) {
        for (const token of line as ShikiToken[]) {
          if (token.color !== undefined) {
            const span = document.createElement('span')
            span.className = ensureColorRule(token.color)
            span.textContent = token.content
            newCode.append(span)
          } else {
            newCode.append(token.content)
          }
        }
        newCode.append('\n')
      }
      // 移除末尾多余换行，保留 pre 语义
      if (newCode.lastChild?.nodeValue === '\n') newCode.lastChild.remove()
      pre.replaceChildren(newCode)
      highlighted++
    }
    return highlighted > 0
  } catch {
    return false // 加载/高亮失败 → graceful fallback（普通 code block）
  }
}
