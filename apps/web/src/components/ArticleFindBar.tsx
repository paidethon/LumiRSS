/** ArticleFindBar — F13 文内查找条。
 *
 * 输入即在 .lumi-reader-article 的文本节点中查找（不破坏 HTML，
 * reader-find.ts TreeWalker 实现）；显示「n/m 处命中」（0 命中诚实
 * 显示「无结果」）、上一处/下一处循环切换、Escape/× 关闭并清除高亮。
 *
 * 高亮：CSS Custom Highlight API（HighlightRegistry）优先；能力不可用
 * （Firefox 旧版 / jsdom）→ 降级为仅计数 + scrollIntoView 滚到命中处。
 * 查询变化清除旧高亮再重建。 */

import { useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronUp, Search, X } from 'lucide-react'
import {
  clearFindHighlights,
  findMatches,
  highlightMatches,
  revealMatch,
  type FindMatch,
} from '../lib/reader-find'
import { IconButton } from './ui/IconButton'

export interface ArticleFindBarProps {
  open: boolean
  onClose: () => void
  /** 取查找根（.lumi-reader-article；惰性调用）。 */
  getRoot: () => HTMLElement | null
}

export default function ArticleFindBar({ open, onClose, getRoot }: ArticleFindBarProps) {
  const [query, setQuery] = useState('')
  const [total, setTotal] = useState(0)
  const [current, setCurrent] = useState(0) // 0 基；显示时 +1
  const matchesRef = useRef<FindMatch[]>([])
  const inputRef = useRef<HTMLInputElement | null>(null)

  // 打开时聚焦输入框（键盘路径直接可输入）。
  useEffect(() => {
    if (open) inputRef.current?.focus()
    else {
      // 关闭（Escape/×/切文章）→ 清除高亮，绝无残留。
      clearFindHighlights()
      matchesRef.current = []
    }
  }, [open])

  // 查询变化 → 清旧高亮 → 重新查找（组件卸载时兜底清理）。
  useEffect(() => {
    if (!open) return
    clearFindHighlights()
    const trimmed = query.trim()
    const root = trimmed === '' ? null : getRoot()
    if (root === null) {
      matchesRef.current = []
      setTotal(0)
      setCurrent(0)
      return
    }
    const matches = findMatches(root, trimmed)
    matchesRef.current = matches
    setTotal(matches.length)
    setCurrent(0)
    if (matches.length > 0) {
      // 高亮不可用（返回 false）= 降级路径：仅计数，靠 revealMatch 滚动定位。
      highlightMatches(matches, 0)
      revealMatch(matches[0]!)
    }
    return () => {
      clearFindHighlights()
      matchesRef.current = []
    }
  }, [query, open, getRoot])

  if (!open) return null

  const goto = (delta: 1 | -1) => {
    const matches = matchesRef.current
    if (matches.length === 0) return
    const next = (current + delta + matches.length) % matches.length
    setCurrent(next)
    highlightMatches(matches, next)
    revealMatch(matches[next]!)
  }

  const close = () => {
    clearFindHighlights()
    matchesRef.current = []
    onClose()
  }

  return (
    <div
      role="search"
      aria-label="文内查找"
      className="absolute left-1/2 top-3 z-30 flex w-[min(92%,28rem)] -translate-x-1/2 items-center gap-1 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] p-1.5 shadow-[var(--lumi-shadow-popover)]"
    >
      <Search aria-hidden className="mx-1.5 size-4 shrink-0 text-[var(--lumi-text-secondary)]" />
      <input
        ref={inputRef}
        type="text"
        value={query}
        aria-label="查找正文"
        placeholder="在正文中查找…"
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            e.stopPropagation()
            close()
          } else if (e.key === 'Enter') {
            e.preventDefault()
            goto(e.shiftKey ? -1 : 1)
          }
        }}
        className="min-h-8 w-full min-w-0 bg-transparent text-sm text-[var(--lumi-text-primary)] outline-none placeholder:text-[var(--lumi-text-tertiary)]"
      />
      {/* 命中计数（aria-live）：0 命中诚实显示「无结果」。 */}
      <span
        aria-live="polite"
        className="shrink-0 whitespace-nowrap px-1 text-xs tabular-nums text-[var(--lumi-text-secondary)]"
        data-lumi-find-status=""
      >
        {query.trim() === '' ? '' : total === 0 ? '无结果' : `${current + 1}/${total} 处命中`}
      </span>
      <IconButton size="sm" icon={<ChevronUp aria-hidden className="size-4" />} label="上一处" touch disabled={total === 0} onClick={() => goto(-1)} />
      <IconButton size="sm" icon={<ChevronDown aria-hidden className="size-4" />} label="下一处" touch disabled={total === 0} onClick={() => goto(1)} />
      <IconButton size="sm" icon={<X aria-hidden className="size-4" />} label="关闭查找" touch onClick={close} />
    </div>
  )
}
