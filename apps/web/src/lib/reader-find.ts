/** reader-find — F13 文内查找（不破坏 HTML 的正文文本匹配 + 高亮）。
 *
 * 匹配：TreeWalker 遍历文本节点（跳过 script/style/复制按钮），大小写
 * 不敏感；跨元素的查询不命中（诚实范围：单文本节点内匹配）。
 *
 * 高亮：优先 CSS Custom Highlight API（HighlightRegistry，Chrome/
 * Safari 16.4+，零 DOM 侵入）；能力不可用（含 jsdom）→ 降级为仅计数
 * + scrollIntoView 滚到命中处。所有注册名集中定义，样式在 index.css
 * 的 ::highlight() 规则。 */

export interface FindMatch {
  node: Text
  start: number
  end: number
}

/** 高亮注册名（index.css 中 ::highlight(lumi-find-all/current) 消费）。 */
export const FIND_ALL_HIGHLIGHT_NAME = 'lumi-find-all'
export const FIND_CURRENT_HIGHLIGHT_NAME = 'lumi-find-current'

/** 查找时跳过的子树（不可见/非正文本）。 */
const SKIP_SELECTOR = 'script, style, noscript, .code-copy-btn'

/** 能力检测：CSS Custom Highlight API 是否可用（运行时逐级探测，
 * jsdom / 旧浏览器返回 false → 调用方走降级路径）。 */
export function supportsCssHighlights(): boolean {
  if (typeof CSS === 'undefined' || !('highlights' in CSS)) return false
  return typeof Highlight === 'function'
}

function rangeOf(match: FindMatch): Range {
  const range = document.createRange()
  range.setStart(match.node, match.start)
  range.setEnd(match.node, match.end)
  return range
}

/** 在 root 内查找查询串的全部命中（按文档序）。查询首尾去空格后
 * 大小写不敏感；空查询返回 []。 */
export function findMatches(root: HTMLElement, query: string): FindMatch[] {
  const needle = query.trim().toLowerCase()
  if (needle === '') return []
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node: Node): number {
      const parent = node.parentElement
      if (parent === null || parent.closest(SKIP_SELECTOR) !== null) {
        return NodeFilter.FILTER_REJECT
      }
      return NodeFilter.FILTER_ACCEPT
    },
  })
  const matches: FindMatch[] = []
  for (
    let node = walker.nextNode() as Text | null;
    node !== null;
    node = walker.nextNode() as Text | null
  ) {
    const haystack = (node.textContent ?? '').toLowerCase()
    let index = haystack.indexOf(needle)
    while (index !== -1) {
      matches.push({ node, start: index, end: index + needle.length })
      index = haystack.indexOf(needle, index + needle.length)
    }
  }
  return matches
}

/** 注册高亮（全部命中 + 当前命中）；能力不可用返回 false（降级信号，
 * 调用方仍可计数 + 滚动定位）。查询变化时先 clearFindHighlights()。 */
export function highlightMatches(
  matches: FindMatch[],
  activeIndex: number,
): boolean {
  if (!supportsCssHighlights() || matches.length === 0) return false
  const active = Math.min(Math.max(activeIndex, 0), matches.length - 1)
  CSS.highlights.set(
    FIND_ALL_HIGHLIGHT_NAME,
    new Highlight(...matches.map((m) => rangeOf(m))),
  )
  CSS.highlights.set(FIND_CURRENT_HIGHLIGHT_NAME, new Highlight(rangeOf(matches[active]!)))
  return true
}

/** 清除查找高亮（幂等）。 */
export function clearFindHighlights(): void {
  if (!supportsCssHighlights()) return
  CSS.highlights.delete(FIND_ALL_HIGHLIGHT_NAME)
  CSS.highlights.delete(FIND_CURRENT_HIGHLIGHT_NAME)
}

/** 把命中处滚进视口中央（高亮/降级共用；scrollIntoView 会滚动最近的
 * 可滚动祖先，即 Reader 滚动容器）。无该 API 的环境（jsdom）静默跳过。 */
export function revealMatch(match: FindMatch): void {
  const parent = match.node.parentElement
  if (parent !== null && typeof parent.scrollIntoView === 'function') {
    parent.scrollIntoView({ block: 'center' })
  }
}
