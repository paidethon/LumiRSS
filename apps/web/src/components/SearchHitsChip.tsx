/** SearchHitsChip — F072 命中定位 chip（Reader 顶部）。
 *
 * 搜索结果打开的文章：若有暂存的正文命中偏移 →
 * - 全部可定位 → chip「命中 N 处」+「下一处」循环选区跳转；
 * - 任一处无法定位（正文已变化）→ chip 显示「原文已变化」不跳错；
 * - 无命中（仅标题命中）→ 不渲染（诚实）。
 *
 * 正文为异步管线渲染：定位在 detailReady 后重试数次；最终仍无法
 * 全部定位 → 诚实降级。 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Crosshair } from 'lucide-react'
import {
  collectHitRanges,
  selectRange,
  takeSearchHits,
  type SearchHit,
} from '../lib/search-hit-locate'

type Status = 'pending' | 'ready' | 'degraded' | 'none'

export function SearchHitsChip({
  entryRef,
  getRoot,
  detailReady,
}: {
  entryRef: string | null
  /** 返回正文容器（article 根）；未就绪时 null。 */
  getRoot: () => Element | null
  /** Detail 已到达（触发定位尝试）。 */
  detailReady: boolean
}) {
  const [hits, setHits] = useState<SearchHit[] | null>(null)
  const [status, setStatus] = useState<Status>('pending')
  const [current, setCurrent] = useState(0)
  const rangesRef = useRef<Range[]>([])
  const attemptsRef = useRef(0)
  const timersRef = useRef<number[]>([])

  // entryRef 变化：取走暂存命中（读取即清除）
  useEffect(() => {
    if (entryRef === null) return
    setHits(takeSearchHits(entryRef))
    setStatus('pending')
    setCurrent(0)
    rangesRef.current = []
    attemptsRef.current = 0
  }, [entryRef])

  const attempt = useCallback(() => {
    if (hits === null || hits.length === 0 || entryRef === null) return
    const root = getRoot()
    if (root === null) return
    attemptsRef.current += 1
    const { ranges } = collectHitRanges(root, hits)
    const renderedEnough = (root.textContent?.length ?? 0) >= hits[hits.length - 1].offset + 1
if (ranges.length === hits.length) {
      rangesRef.current = ranges
      setStatus('ready')
      setCurrent(0)
      selectRange(ranges[0])
      return
    }
    if (renderedEnough || attemptsRef.current >= 4) {
      // 正文已渲染但命中无法全部定位 → 原文已变化（诚实降级，不跳错）
      setStatus('degraded')
      return
    }
    setStatus('pending') // 尚未渲染完，等待重试
  }, [hits, entryRef, getRoot])

  useEffect(() => {
    if (!detailReady || hits === null || hits.length === 0) return
    attempt()
    for (const t of timersRef.current) window.clearTimeout(t)
    timersRef.current = [window.setTimeout(attempt, 250), window.setTimeout(attempt, 900), window.setTimeout(attempt, 2000)]
    return () => {
      for (const t of timersRef.current) window.clearTimeout(t)
    }
  }, [detailReady, hits, attempt])

  if (hits === null || hits.length === 0) return null
  if (status === 'pending') return null

  if (status === 'degraded') {
    return (
      <div data-lumi-search-hits="" className="absolute left-1/2 top-3 z-10 -translate-x-1/2">
        <span
          role="status"
          className="inline-flex items-center gap-1 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] px-2.5 py-1 text-xs text-[var(--lumi-text-secondary)] shadow-[var(--lumi-shadow-popover)]"
        >
          <Crosshair aria-hidden className="size-3.5" />
          原文已变化，无法定位命中位置
        </span>
      </div>
    )
  }

  const jumpTo = (index: number) => {
    const range = rangesRef.current[index]
    if (range === undefined) return
    selectRange(range)
  }

  return (
    <div data-lumi-search-hits="" className="absolute left-1/2 top-3 z-10 -translate-x-1/2">
      <span className="inline-flex items-center gap-1 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] px-2.5 py-1 text-xs text-[var(--lumi-text-secondary)] shadow-[var(--lumi-shadow-popover)]">
        <Crosshair aria-hidden className="size-3.5" />
        命中 {hits.length} 处
        <button
          type="button"
          aria-label="下一处命中"
          onClick={() => {
            const next = (current + 1) % rangesRef.current.length
            setCurrent(next)
            jumpTo(next)
          }}
          className="ms-1 rounded-full px-1.5 py-0.5 font-medium text-[var(--lumi-accent-text)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        >
          下一处
        </button>
      </span>
    </div>
  )
}
