/** highlight-text — F28 搜索命中高亮（安全实现）。
 *
 * 安全边界：纯文本分词 + 片段切分，命中片段用 <mark> 包裹——绝不使用
 * dangerouslySetInnerHTML，不构造正则（terms 来自用户输入，indexOf
 * 扫描天然免疫正则注入）；DOMPurify 边界不受影响（这里只有文本节点
 * 与 <mark>）。
 *
 * 匹配语义：大小写不敏感（casefold = toLowerCase 比较）；terms 为空、
 * enabled=false 或文本为空时原样返回（零残留——组件是纯函数渲染，
 * terms 变化即重算，不会残留上一次的 <mark>）。 */

import { Fragment } from 'react'

export interface HighlightSegment {
  text: string
  hit: boolean
}

/** 搜索词分词：按空白切分、去空。（供列表/结果组件与测试共用。） */
export function splitTerms(query: string): string[] {
  return query
    .split(/\s+/)
    .map((t) => t.trim())
    .filter((t) => t.length > 0)
}

/** 纯函数：把文本切成 [{text, hit}] 片段；命中区间大小写不敏感、
 * 跨 terms 合并重叠。无命中时返回单段未命中（text 原样）。 */
export function splitHighlightSegments(text: string, terms: string[]): HighlightSegment[] {
  if (text === '') return []
  const lowered = terms
    .map((t) => t.toLowerCase())
    .filter((t) => t.length > 0)
  if (lowered.length === 0) return [{ text, hit: false }]

  const lowerText = text.toLowerCase()
  const ranges: Array<[number, number]> = []
  for (const term of lowered) {
    let idx = lowerText.indexOf(term)
    while (idx !== -1) {
      ranges.push([idx, idx + term.length])
      idx = lowerText.indexOf(term, idx + term.length)
    }
  }
  if (ranges.length === 0) return [{ text, hit: false }]

  ranges.sort((a, b) => a[0] - b[0])
  const merged: Array<[number, number]> = []
  for (const range of ranges) {
    const last = merged[merged.length - 1]
    if (last !== undefined && range[0] <= last[1]) {
      last[1] = Math.max(last[1], range[1])
    } else {
      merged.push([range[0], range[1]])
    }
  }

  const segments: HighlightSegment[] = []
  let cursor = 0
  for (const [start, end] of merged) {
    if (start > cursor) segments.push({ text: text.slice(cursor, start), hit: false })
    segments.push({ text: text.slice(start, end), hit: true })
    cursor = end
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor), hit: false })
  return segments
}

/** F28 高亮组件：enabled=false 或无 terms 时原样返回文本（无 <mark>）。
 * 搜索结果标题与摘要共用；markClassName 供调用方注入语义 token 样式。 */
export function HighlightText({
  text,
  terms,
  enabled = true,
  markClassName,
}: {
  text: string
  terms: string[]
  enabled?: boolean
  /** <mark> 的附加 class（语义 token 着色用；缺省浏览器默认样式） */
  markClassName?: string
}) {
  if (!enabled || terms.length === 0) {
    return <Fragment>{text}</Fragment>
  }
  const segments = splitHighlightSegments(text, terms)
  return (
    <Fragment>
      {segments.map((segment, index) =>
        segment.hit ? (
          <mark key={index} className={markClassName}>
            {segment.text}
          </mark>
        ) : (
          <Fragment key={index}>{segment.text}</Fragment>
        ),
      )}
    </Fragment>
  )
}
