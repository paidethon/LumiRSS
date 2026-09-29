/** ArticleFindBar — F13 文内查找条。
 *
 * 输入即在 .lumi-reader-article 的文本节点中查找（不破坏 HTML，
 * reader-find.ts TreeWalker 实现）；显示「n/m 处命中」（0 命中诚实
 * 显示「无结果」）、上一处/下一处循环切换、Escape/× 关闭并清除高亮。
 *
 * 高亮：CSS Custom Highlight API（HighlightRegistry）优先；能力不可用
 * （Firefox 旧版 / jsdom）→ 降级为仅计数 + scrollIntoView 滚到命中处。
 * 查询变化清除旧高亮再重建。
 *
 * NEW-356：查找范围（双层/原文/译文）——正文含译文 overlay
 * （.lb-translation，双语/仅译文视图）时显示范围选择；默认「双层」=
 * 既有行为。译文层探测跟随真实 DOM（每次查找重新探测；关闭时复位），
 * 范围停在「译文」而译文层消失时自动回退「双层」。 */

import { useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronUp, Search, X } from 'lucide-react'
import {
  clearFindHighlights,
  findMatches,
  hasTranslationLayer,
  highlightMatches,
  revealMatch,
  type FindMatch,
  type FindScope,
} from '../lib/reader-find'
import { IconButton } from './ui/IconButton'

export interface ArticleFindBarProps {
  open: boolean
  onClose: () => void
  /** 取查找根（.lumi-reader-article；惰性调用）。 */
  getRoot: () => HTMLElement | null
}

/** NEW-356：范围选项（标签与 FindScope 一一对应）。 */
const FIND_SCOPE_OPTIONS: ReadonlyArray<{ value: FindScope; label: string }> = [
  { value: 'all', label: '双层' },
  { value: 'original', label: '原文' },
  { value: 'translated', label: '译文' },
]

export default function ArticleFindBar({ open, onClose, getRoot }: ArticleFindBarProps) {
  const [query, setQuery] = useState('')
  const [scope, setScope] = useState<FindScope>('all')
  const [total, setTotal] = useState(0)
  const [current, setCurrent] = useState(0) // 0 基；显示时 +1
  // NEW-356：译文层存在性——每次查找按真实 DOM 探测（overlay 注入/
  // 移除后跟随；纯原文态不出现范围选择）。
  const [translationAvailable, setTranslationAvailable] = useState(false)
  const matchesRef = useRef<FindMatch[]>([])
  const inputRef = useRef<HTMLInputElement | null>(null)

  // 译文层消失（切回原文视图）而范围停在译文 → 回退双层（诚实，不空转）。
  useEffect(() => {
    if (!translationAvailable && scope === 'translated') setScope('all')
  }, [translationAvailable, scope])

  // 打开时聚焦输入框（键盘路径直接可输入）。
  useEffect(() => {
    if (open) inputRef.current?.focus()
    else {
      // 关闭（Escape/×/切文章）→ 清除高亮与范围探测，绝无残留。
      clearFindHighlights()
      matchesRef.current = []
      setTranslationAvailable(false)
    }
  }, [open])

  // 查询/范围变化 → 清旧高亮 → 重新查找（组件卸载时兜底清理）。
  // 译文层探测按 getRoot() 的真实正文——与查询是否为空无关（空查询时
  // 范围选择仍需正确显示）。
  useEffect(() => {
    if (!open) return
    clearFindHighlights()
    setTranslationAvailable(hasTranslationLayer(getRoot()))
    const trimmed = query.trim()
    const root = trimmed === '' ? null : getRoot()
    if (root === null) {
      matchesRef.current = []
      setTotal(0)
      setCurrent(0)
      return
    }
    const matches = findMatches(root, trimmed, scope)
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
  }, [query, scope, open, getRoot])

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
          } else if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
            // FIX-012：输入法组合中的 Enter 仅提交候选词，不跳转命中。
            e.preventDefault()
            goto(e.shiftKey ? -1 : 1)
          }
        }}
        className="min-h-8 w-full min-w-0 bg-transparent text-sm text-[var(--lumi-text-primary)] outline-none placeholder:text-[var(--lumi-text-tertiary)]"
      />
      {/* NEW-356：查找范围（仅译文层存在时出现；默认双层 = 既有行为） */}
      {translationAvailable && (
        <div
          role="radiogroup"
          aria-label="查找范围"
          data-lumi-find-scope=""
          className="flex shrink-0 items-center gap-0.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-0.5"
        >
          {FIND_SCOPE_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={scope === option.value}
              onClick={() => setScope(option.value)}
              className={
                scope === option.value
                  ? 'min-h-7 rounded-[var(--lumi-radius-sm)] bg-[var(--lumi-accent-soft)] px-1.5 text-xs font-medium text-[var(--lumi-accent-text)]'
                  : 'min-h-7 rounded-[var(--lumi-radius-sm)] px-1.5 text-xs text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]'
              }
            >
              {option.label}
            </button>
          ))}
        </div>
      )}
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
