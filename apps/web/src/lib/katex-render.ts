/** katex-render — F060 数学公式渲染（动态加载，唯一新依赖）。
 *
 * - 仅在检测到公式时动态 import('katex')（bundle guard 不受影响）；
 * - 检测段内 $...$ 与块级 $$...$$（跳过 code/pre 内部文本）；
 * - renderToString({ throwOnError: false, displayMode, trust: false,
 *   strict: false, output: 'html' })——trust 关闭，\write18/\include
 *   之类宏不可用；产物再过现有净化边界（article-pipeline 终点）；
 * - 渲染失败 → 保留原文文本（诚实降级）；
 * - 超长表达式（>10k 字符）跳过渲染（性能边界）；
 * - KaTeX 输出含 annotation（TeX 原文）——复制段落时公式原文可复制。
 */

const MAX_EXPR_LENGTH = 10_000

/** 检测文本是否可能含公式（跳过 code/pre 的调用方负责过滤文本）。 */
export function containsMathMarker(text: string): boolean {
  return text.includes('$') && (text.includes('$$') || /\$[^$\n]+\$/.test(text))
}

/** 节点子树是否可能含公式（跳过 code/pre/script/style 内部）。 */
export function containsMathIn(root: ParentNode): boolean {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = (node as Text).parentElement
      if (parent === null) return NodeFilter.FILTER_REJECT
      const tag = parent.tagName.toLowerCase()
      if (tag === 'code' || tag === 'pre' || tag === 'script' || tag === 'style') {
        return NodeFilter.FILTER_REJECT
      }
      return NodeFilter.FILTER_ACCEPT
    },
  })
  let current = walker.nextNode()
  while (current !== null) {
    if (containsMathMarker(current.textContent ?? '')) return true
    current = walker.nextNode()
  }
  return false
}

interface MathMatch {
  text: string
  display: boolean
}

/** 从文本中解析第一个公式片段；无公式或超长 → null（保留原文）。 */
export function firstMathMatch(text: string): MathMatch | null {
  const block = text.match(/\$\$([\s\S]+?)\$\$/)
  if (block !== null) {
    const expr = block[1] ?? ''
    if (expr.length > MAX_EXPR_LENGTH) return null
    return { text: block[0], display: true }
  }
  const inline = text.match(/\$([^$\n]+?)\$/)
  if (inline !== null) {
    const expr = inline[1] ?? ''
    if (expr.length > MAX_EXPR_LENGTH) return null
    return { text: inline[0], display: false }
  }
  return null
}

/** 动态加载 katex 并渲染单个公式；失败 → null（调用方保留原文）。 */
export async function renderMath(tex: string, display: boolean): Promise<string | null> {
  try {
    const katex = await import('katex')
    return katex.default.renderToString(tex, {
      throwOnError: false,
      displayMode: display,
      trust: false,
      strict: false,
      output: 'html',
    })
  } catch {
    return null
  }
}

/** 就地渲染整个子树的文本节点中的公式（跳过 code/pre）。 */
export async function renderMathInDom(root: ParentNode): Promise<number> {
  if (!containsMathIn(root)) return 0
  const katex = await import('katex')
  let count = 0
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = (node as Text).parentElement
      if (parent === null) return NodeFilter.FILTER_REJECT
      const tag = parent.tagName.toLowerCase()
      if (tag === 'code' || tag === 'pre' || tag === 'script' || tag === 'style') {
        return NodeFilter.FILTER_REJECT
      }
      return NodeFilter.FILTER_ACCEPT
    },
  })
  const textNodes: Text[] = []
  let current = walker.nextNode()
  while (current !== null) {
    textNodes.push(current as Text)
    current = walker.nextNode()
  }
  for (const node of textNodes) {
    const text = node.textContent ?? ''
    if (!containsMathMarker(text)) continue
    const match = firstMathMatch(text)
    if (match === null) continue
    try {
      const tex = match.display ? match.text.slice(2, -2) : match.text.slice(1, -1)
      const html = katex.default.renderToString(tex, {
        throwOnError: false,
        displayMode: match.display,
        trust: false,
        strict: false,
        output: 'html',
      })
      const parent = node.parentElement
      if (parent === null) continue
      const idx = text.indexOf(match.text)
      const beforeNode = document.createTextNode(text.slice(0, idx))
      const afterNode = document.createTextNode(text.slice(idx + match.text.length))
      const span = document.createElement('span')
      span.innerHTML = html // katex 输出；随后整树过 DOMPurify（最终边界）
      parent.replaceChild(beforeNode, node)
      parent.insertBefore(span, beforeNode.nextSibling)
      parent.insertBefore(afterNode, span.nextSibling)
      count += 1
    } catch {
      // 渲染失败：保留原文文本
    }
  }
  return count
}
