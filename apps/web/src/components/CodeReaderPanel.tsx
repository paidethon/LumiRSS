/** CodeReaderPanel — N057 代码块独立阅读页（灯箱内容模式承载）。
 *
 * 输入是正文渲染后的 <pre>（只读源）；面板内自建展示行：
 * - 行号栏（sticky left，横向滚动时保持可见，纯展示 aria-hidden）；
 * - 面板内搜索：大小写不敏感子串匹配，n/m 计数 + 上一处/下一处跳转
 *   （Enter/Shift+Enter 同义）；当前匹配 mark[data-current]；
 * - 横向滚动保持（whitespace-pre + overflow-auto，跳转只做视口揭示，
 *   不改写源内容）；
 * - 复制：复用 lib/code-copy 的 codeBlockText（textContent 源，空白
 *   原样保留、无行号污染）；成功/失败都有可见反馈并复位（同 pool #04）。
 *
 * 无 dangerouslySetInnerHTML：全部行内容经 React 文本渲染，天然转义。 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, ChevronUp, Copy } from 'lucide-react'
import { codeBlockText } from '../lib/code-copy'
import { findCodeMatches } from '../lib/code-reader'
import { Button } from './ui/Button'

const COPY_FEEDBACK_MS = 1600

/** 把匹配区间折叠成 (text | match) 片段序列（渲染用，无匹配 → 单段）。
 * 片段直接携带全局匹配序号（mark[data-current] 判定用），无匹配为 null。 */
function lineSegments(
  line: string,
  ranges: Array<{ start: number; end: number; globalIndex: number }>,
): Array<{ text: string; globalIndex: number | null }> {
  if (ranges.length === 0) return [{ text: line, globalIndex: null }]
  const segments: Array<{ text: string; globalIndex: number | null }> = []
  let cursor = 0
  for (const range of ranges) {
    if (range.start > cursor) segments.push({ text: line.slice(cursor, range.start), globalIndex: null })
    segments.push({ text: line.slice(range.start, range.end), globalIndex: range.globalIndex })
    cursor = range.end
  }
  if (cursor < line.length) segments.push({ text: line.slice(cursor), globalIndex: null })
  return segments
}

export function CodeReaderPanel({ pre }: { pre: HTMLPreElement }) {
  // 源文本只取一次（面板生命周期内正文不会变化）。
  const [text] = useState(() => codeBlockText(pre))
  const lines = useMemo(() => (text === '' ? [''] : text.split('\n')), [text])
  const [query, setQuery] = useState('')
  const [current, setCurrent] = useState(0)
  const hostRef = useRef<HTMLDivElement | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)

  const matches = useMemo(() => findCodeMatches(lines, query), [lines, query])
  const safeCurrent = matches.length === 0 ? 0 : Math.min(current, matches.length - 1)
  const currentMatch = matches.length > 0 ? matches[safeCurrent] : undefined

  // 查询变化：匹配集合重建后回到第一处。
  useEffect(() => {
    setCurrent(0)
  }, [query])

  // 当前匹配变化 → 纵向居中该行；横向仅做揭示（若已在视口内不动，
  // 不横向居中——避免每跳一处都左右甩动）。
  useEffect(() => {
    const host = hostRef.current
    if (host === null || currentMatch === undefined) return
    const lineEl = host.querySelector<HTMLElement>(`[data-line="${currentMatch.line + 1}"]`)
    if (lineEl === null) return
    const targetTop = lineEl.offsetTop - (host.clientHeight - lineEl.offsetHeight) / 2
    host.scrollTop = Math.max(0, targetTop)
    const markEl = lineEl.querySelector<HTMLElement>('mark')
    if (markEl !== null) {
      const viewLeft = host.scrollLeft
      const viewRight = viewLeft + host.clientWidth
      const markLeft = markEl.offsetLeft
      const markRight = markLeft + markEl.offsetWidth
      if (markLeft < viewLeft || markRight > viewRight) {
        host.scrollLeft = Math.max(0, markLeft - host.clientWidth / 2)
      }
    }
  }, [currentMatch])

  function step(delta: 1 | -1) {
    if (matches.length === 0) return
    setCurrent((c) => (c + delta + matches.length) % matches.length)
  }

  async function copyCode() {
    try {
      await navigator.clipboard.writeText(text)
      setFeedback('已复制 ✓')
    } catch {
      setFeedback('复制失败')
    }
    window.setTimeout(() => setFeedback(null), COPY_FEEDBACK_MS)
  }

  // 每行的匹配区间（含全局序号，供 mark[data-current] 判定）。
  const rangesByLine = useMemo(() => {
    const map = new Map<number, Array<{ start: number; end: number; globalIndex: number }>>()
    matches.forEach((m, globalIndex) => {
      const list = map.get(m.line) ?? []
      list.push({ start: m.start, end: m.end, globalIndex })
      map.set(m.line, list)
    })
    return map
  }, [matches])

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* 工具栏：源行数 + 面板内搜索 + 复制 */}
      <div
        className="flex flex-wrap items-center gap-2 border-b border-[var(--lumi-border)] px-4 py-2"
        data-testid="code-reader-toolbar"
      >
        <span className="text-sm font-medium text-[var(--lumi-text-primary)]">
          代码（{lines.length} 行，可横向滚动）
        </span>
        <span className="flex-1" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              step(e.shiftKey ? -1 : 1)
            }
          }}
          placeholder="搜索代码"
          aria-label="搜索代码"
          data-testid="code-reader-search"
          className="h-8 w-36 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-xs text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        />
        <span aria-live="polite" data-testid="code-reader-match-count" className="min-w-16 text-xs tabular-nums text-[var(--lumi-text-secondary)]">
          {query.trim() === '' ? '' : matches.length === 0 ? '无结果' : `${safeCurrent + 1}/${matches.length} 处命中`}
        </span>
        <Button size="sm" variant="secondary" disabled={matches.length === 0} aria-label="上一处匹配" onClick={() => step(-1)}>
          <ChevronUp aria-hidden className="size-3.5" />
          上一处
        </Button>
        <Button size="sm" variant="secondary" disabled={matches.length === 0} aria-label="下一处匹配" onClick={() => step(1)}>
          <ChevronDown aria-hidden className="size-3.5" />
          下一处
        </Button>
        <Button size="sm" variant="secondary" onClick={() => void copyCode()}>
          <Copy aria-hidden className="size-3.5" />
          复制
        </Button>
        {feedback !== null && (
          <span role="status" className="text-xs text-[var(--lumi-accent-text)]">
            {feedback}
          </span>
        )}
      </div>
      {/* 行号 + 代码行：whitespace-pre 保持空白/缩进；overflow-auto 保持
          横向滚动；行号栏 sticky left（横向滚动时可见）。 */}
      <div
        ref={hostRef}
        data-testid="code-reader-host"
        data-code-lines={lines.length}
        className="relative min-h-0 flex-1 overflow-auto bg-[var(--lumi-surface)] py-2 font-mono text-xs leading-5"
      >
        {lines.map((line, lineIndex) => {
          const ranges = rangesByLine.get(lineIndex) ?? []
          return (
            <div key={lineIndex} data-line={lineIndex + 1} className="flex">
              <span
                aria-hidden="true"
                className="lumi-code-gutter sticky left-0 w-12 shrink-0 select-none border-r border-[var(--lumi-border)] pr-2 text-right tabular-nums text-[var(--lumi-text-tertiary)]"
              >
                {lineIndex + 1}
              </span>
              <span className="whitespace-pre pl-3 pr-6 text-[var(--lumi-text-primary)]">
                {lineSegments(line, ranges).map((segment, segIndex) =>
                  segment.globalIndex !== null ? (
                    <mark
                      key={segIndex}
                      data-current={segment.globalIndex === safeCurrent ? 'true' : undefined}
                      className="lumi-code-match"
                    >
                      {segment.text}
                    </mark>
                  ) : (
                    <span key={segIndex}>{segment.text}</span>
                  ),
                )}
                {/* 空行占位：保持行高（空字符串行高为 0） */}
                {line === '' && ranges.length === 0 ? '\u200b' : null}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
