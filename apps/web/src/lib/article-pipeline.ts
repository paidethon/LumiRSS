/** article-pipeline — Reader 正文展示变换管线（0012 Gate 4 安全模型）。
 *
 * 旧 invariant（0006）是「sanitize 后字符串不得再修改」；0012 的简繁
 * 转换 / Bionic / 代码高亮都需要 presentation transform，因此升级为：
 *
 * ```text
 * raw RSS HTML
 *   ↓ DOMParser → inert document（不执行任何东西）
 * controlled presentation transforms（DOM API：textContent/createElement）
 *   ↓ DOMPurify.sanitize（最终安全边界，serialize 后）
 *   ↓ ArticleContent dangerouslySetInnerHTML（唯一注入点）
 * ```
 *
 * 硬规则（Spec 安全模型）：
 * - DOMPurify 仍是最终可信边界：transforms 产生的所有节点在注入前
 *   整体再过一次 sanitize；
 * - transforms 只用 DOM API（createElement/textContent/setAttribute 白名单
 *   属性），禁止 innerHTML 拼接不可信数据；
 * - 不执行 script、不保留 event handler、不放开 iframe/arbitrary style/
 *   javascript: URL——这些由 sanitize 统一移除，transforms 也不得引入；
 * - 原始 RSS HTML 永不直接进入 React。
 *
 * 转换开关均幂等：每次渲染从 raw HTML 重新构建，切换设置 = 重跑管线，
 * 不存在「同一 DOM 反复叠加」的膨胀问题（AC：切回原文完全恢复）。 */

import { sanitizeArticleHtml } from './sanitize-article-html'
import { containsCodeBlock, highlightCodeBlocks } from './code-highlight'
import type { ReaderChineseConversion } from '../store/app-settings'

// ---- 有界展示缓存（性能：Reader 按 entryRef 重挂载是防泄漏的既定架构，
// 但重挂载不该重复付出整个正文的 sanitize / transform 成本——快速来回
// 切换缓存文章时尤其明显。key 全部用精确输入字符串，绝不做哈希/截断，
// 杜绝碰撞渲染错内容。） ----

/** sanitize 基线缓存（sync 首帧路径），key = 原始 HTML。 */
const sanitizeCache = new Map<string, string>()
/** 完整管线输出缓存（值为 Promise，并发去重），key = 选项 JSON + 原始 HTML。 */
const pipelineCache = new Map<string, Promise<string>>()
const SANITIZE_CACHE_MAX = 12
const PIPELINE_CACHE_MAX = 8

function cacheGetOrPut(
  cache: Map<string, string>,
  max: number,
  key: string,
  compute: () => string,
): string {
  const hit = cache.get(key)
  if (hit !== undefined) {
    // 刷新插入顺序（Map 迭代序 = 插入序，实现简易 LRU 逐出）
    cache.delete(key)
    cache.set(key, hit)
    return hit
  }
  const value = compute()
  cache.set(key, value)
  if (cache.size > max) {
    const oldest = cache.keys().next().value
    if (oldest !== undefined) cache.delete(oldest)
  }
  return value
}

/** 带缓存的 sanitize 基线（同一篇正文在 Reader 重挂载时不再重复清洗）。 */
export function sanitizeArticleHtmlCached(html: string): string {
  return cacheGetOrPut(sanitizeCache, SANITIZE_CACHE_MAX, html, () =>
    sanitizeArticleHtml(html),
  )
}

// ---- 中文简繁转换（OpenCC，dynamic import，仅启用时加载） ----

type OpenCCConverter = (text: string) => string
let converterCache: Partial<Record<ReaderChineseConversion, OpenCCConverter | null>> = {}

const OPENCC_OPTIONS: Record<
  Exclude<ReaderChineseConversion, 'off'>,
  { from: 'cn'; to: 'twp' | 'hk' } | { from: 'cn'; to: 't' } | { from: 't', to: 'cn' }
> = {
  s2t: { from: 'cn', to: 't' },
  t2s: { from: 't', to: 'cn' },
  tw: { from: 'cn', to: 'twp' },
  hk: { from: 'cn', to: 'hk' },
}

async function getConverter(mode: ReaderChineseConversion): Promise<OpenCCConverter | null> {
  if (mode === 'off') return null
  const cached = converterCache[mode]
  if (cached !== undefined) return cached
  try {
    // 按方向拆包（性能预算）：t2cn 仅 109KB；cn2t ~1.1MB
    //（其中 STPhrases 词典 ~1MB 是简→繁的固有成本）。两者都是
    // dynamic import，未启用时零加载。
    const opts = OPENCC_OPTIONS[mode]
    const mod =
      mode === 't2s' ? await import('opencc-js/t2cn') : await import('opencc-js/cn2t')
    const converter = mod.Converter(opts)
    converterCache[mode] = converter
    return converter
  } catch {
    converterCache[mode] = null
    return null
  }
}

/** 转换器缓存清理（测试用；页面切换文章不需要清）。 */
export function clearConverterCache(): void {
  converterCache = {}
}

/** 不做简繁转换的元素：代码内容 + 嵌入控件。 */
const CONVERSION_SKIP_TAGS = new Set([
  'CODE',
  'PRE',
  'KBD',
  'SAMP',
  'SCRIPT',
  'STYLE',
  'BUTTON',
  'INPUT',
  'TEXTAREA',
  'SELECT',
])

/** 走 TreeWalker 只改 text node 的 data —— HTML 标签 / 属性 / URL
 * 天然不受影响（AC：代码内容默认不转换）。 */
function convertTextNodes(root: Node, convert: OpenCCConverter): void {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement
      if (parent === null) return NodeFilter.FILTER_REJECT
      return CONVERSION_SKIP_TAGS.has(parent.tagName)
        ? NodeFilter.FILTER_REJECT
        : NodeFilter.FILTER_ACCEPT
    },
  })
  for (let n = walker.nextNode(); n !== null; n = walker.nextNode()) {
    const text = n.nodeValue ?? ''
    if (text.trim() !== '') n.nodeValue = convert(text)
  }
}

// ---- Bionic 词首强调（实验性，Gate 9） ----

/** 仅匹配拉丁词首部分（含常见撇号/连字符词内边界不拆）。 */
const LATIN_WORD_RE = /[A-Za-z][A-Za-z'’]*/g

/** 跳过容器（语义/视觉不适用）：代码、按钮、标题。 */
const BIONIC_SKIP_TAGS = new Set([
  'CODE',
  'PRE',
  'KBD',
  'SAMP',
  'BUTTON',
  'A',
  'H1',
  'H2',
  'H3',
  'H4',
  'H5',
  'H6',
  'SCRIPT',
  'STYLE',
])

/** 对拉丁词首做视觉强调（<b class="lumi-bionic">）。幂等安全：每次
 * 渲染从 raw HTML 重建；<b> 不嵌套 <strong>（只包 plain text node）。
 * 不给 CJK 字符套标签——TreeWalker 只处理纯拉丁词首的 text node。 */
function applyBionic(root: Node): void {
  const targets: Text[] = []
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement
      if (parent === null) return NodeFilter.FILTER_REJECT
      if (BIONIC_SKIP_TAGS.has(parent.tagName)) return NodeFilter.FILTER_REJECT
      // 已在 <b class="lumi-bionic"> 内（不应发生，防御）
      if (parent.tagName === 'B' && parent.classList.contains('lumi-bionic')) {
        return NodeFilter.FILTER_REJECT
      }
      return /[A-Za-z]/.test(node.nodeValue ?? '') ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT
    },
  })
  for (let n = walker.nextNode(); n !== null; n = walker.nextNode()) {
    targets.push(n as Text)
  }
  for (const textNode of targets) {
    const text = textNode.nodeValue ?? ''
    if (text.trim() === '') continue
    LATIN_WORD_RE.lastIndex = 0
    let match: RegExpExecArray | null
    const pieces: (string | HTMLElement)[] = []
    let last = 0
    while ((match = LATIN_WORD_RE.exec(text)) !== null) {
      if (match.index > last) pieces.push(text.slice(last, match.index))
      const word = match[0]
      // 词首强调长度：2 字符以内全强调；3–4 取前半；更长取 ~40%
      const headLen = word.length <= 2 ? word.length : word.length <= 4 ? Math.ceil(word.length / 2) : Math.ceil(word.length * 0.4)
      const b = document.createElement('b')
      b.className = 'lumi-bionic'
      b.textContent = word.slice(0, headLen)
      pieces.push(b, word.slice(headLen))
      last = match.index + word.length
    }
    if (pieces.length === 0) continue
    if (last < text.length) pieces.push(text.slice(last))
    const frag = document.createDocumentFragment()
    for (const p of pieces) frag.append(p)
    textNode.replaceWith(frag)
  }
}

// ---- 管线入口 ----

export interface ArticlePipelineOptions {
  conversion: ReaderChineseConversion
  bionic: boolean
  /** 代码高亮：null = 关闭；否则为已解析的 shiki 主题名 */
  codeTheme: string | null
}

/** raw RSS HTML → inert DOM → transforms → DOMPurify 终点。
 * 返回可直接注入 dangerouslySetInnerHTML 的安全字符串。
 * transform 全部失败/未启用时退化为纯 sanitize（= 0006 行为）。 */
export async function renderArticleHtml(
  rawHtml: string,
  options: ArticlePipelineOptions,
): Promise<string> {
  const needsConversion = options.conversion !== 'off'
  const needsBionic = options.bionic
  // 无 code 文章不加载 shiki（性能预算：不用 → 不加载）
  const needsHighlight =
    options.codeTheme !== null && containsCodeBlock(rawHtml)
  if (!needsConversion && !needsBionic && !needsHighlight) {
    return sanitizeArticleHtml(rawHtml)
  }

  // DOMParser 产出 inert document：不执行 script、不加载资源
  const doc = new DOMParser().parseFromString(rawHtml, 'text/html')

  if (needsConversion) {
    const converter = await getConverter(options.conversion)
    if (converter !== null) convertTextNodes(doc.body, converter)
  }
  if (needsBionic) applyBionic(doc.body)
  if (needsHighlight) {
    await highlightCodeBlocks(doc.body, options.codeTheme as string)
  }

  // 最终安全边界：transform 后的整个 DOM serialize → DOMPurify。
  // transforms 可能引入的任何意外标记在这里被统一清洗。
  return sanitizeArticleHtml(doc.body.innerHTML)
}

/** 测试用：清空展示缓存（与 clearConverterCache 同一模式）。 */
export function clearArticleHtmlCaches(): void {
  sanitizeCache.clear()
  pipelineCache.clear()
}

/** renderArticleHtml 的缓存包装。缓存值为 Promise：并发同 key 请求
 * 天然去重；key 含全部影响输出的输入（rawHtml / conversion / bionic /
 * codeTheme），设置变化 = 不同 key。管线失败不落缓存（可重试）。 */
export function renderArticleHtmlCached(
  rawHtml: string,
  options: ArticlePipelineOptions,
): Promise<string> {
  const key = JSON.stringify(options) + '\u0000' + rawHtml
  const hit = pipelineCache.get(key)
  if (hit !== undefined) return hit
  const promise = renderArticleHtml(rawHtml, options)
  pipelineCache.set(key, promise)
  if (pipelineCache.size > PIPELINE_CACHE_MAX) {
    const oldest = pipelineCache.keys().next().value
    if (oldest !== undefined && oldest !== key) pipelineCache.delete(oldest)
  }
  void promise.catch(() => {
    if (pipelineCache.get(key) === promise) pipelineCache.delete(key)
  })
  return promise
}
