/** SearchHitsChip — F072 命中定位 chip（Reader 顶部）+ N146 双语命中定位。
 *
 * 搜索结果打开的文章：若有暂存的正文命中偏移 →
 * - 全部可定位 → chip「命中 N 处」+「下一处」循环选区跳转；
 * - 任一处无法定位（正文已变化）→ chip 显示「原文已变化」不跳错；
 * - 无命中（仅标题命中）→ 不渲染（诚实）。
 *
 * N146 双语补位：翻译 overlay 激活（双语/仅译文）且当前命中的块有
 * 配对译文（data-lb 配对）→ 命中上下文同时展示 原文 + 译文 片段，
 * 跳转定位到配对（原文选区 + 译文临时高亮一并可见）。
 *
 * 正文为异步管线渲染：定位在 detailReady 后重试数次；overlay 激活
 * （viewMode 切换）后重新定位一次以拿到配对关系；最终仍无法全部
 * 定位 → 诚实降级。 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Crosshair, Languages } from 'lucide-react'
import {
  clearTranslationHit,
  collectHitPairLocations,
  hitSnippet,
  markTranslationHit,
  selectRange,
  takeSearchHits,
  type HitPairLocation,
  type SearchHit,
} from '../lib/search-hit-locate'
import type { ReaderViewMode } from '../lib/translation-blocks'

type Status = 'pending' | 'ready' | 'degraded' | 'none'

export function SearchHitsChip({
  entryRef,
  getRoot,
  detailReady,
  viewMode = 'original',
}: {
  entryRef: string | null
  /** 返回正文容器（article 根）；未就绪时 null。 */
  getRoot: () => Element | null
  /** Detail 已到达（触发定位尝试）。 */
  detailReady: boolean
  /** N146：当前阅读视图模式（非 original = 译文 overlay 可能已注入）。 */
  viewMode?: ReaderViewMode
}) {
  const [hits, setHits] = useState<SearchHit[] | null>(null)
  const [locations, setLocations] = useState<(HitPairLocation | null)[]>([])
  const [status, setStatus] = useState<Status>('pending')
  const [current, setCurrent] = useState(0)
  const locationsRef = useRef<(HitPairLocation | null)[]>([])
  const markedRef = useRef<HTMLElement | null>(null)
  const attemptsRef = useRef(0)
  const timersRef = useRef<number[]>([])

  // entryRef 变化：取走暂存命中（读取即清除）
  useEffect(() => {
    if (entryRef === null) return
    setHits(takeSearchHits(entryRef))
    setStatus('pending')
    setCurrent(0)
    locationsRef.current = []
    setLocations([])
    attemptsRef.current = 0
  }, [entryRef])

  const jumpTo = (index: number, override?: (HitPairLocation | null)[]) => {
    const list = override ?? locationsRef.current
    const location = list[index]
    if (location === null || location === undefined) return
    selectRange(location.range)
    if (markedRef.current !== null) {
      clearTranslationHit(markedRef.current)
      markedRef.current = null
    }
    if (location.translation !== null) {
      // N146：定位到配对——译文滚入视野并临时高亮（原文选区仍在）。
      location.translation.scrollIntoView?.({ block: 'center' })
      markTranslationHit(location.translation)
      markedRef.current = location.translation
    }
  }

  const attempt = useCallback(() => {
    if (hits === null || hits.length === 0 || entryRef === null) return
    const root = getRoot()
    if (root === null) return
    attemptsRef.current += 1
    const result = collectHitPairLocations(root, hits)
    const last = hits[hits.length - 1]
    const renderedEnough = (root.textContent?.length ?? 0) >= last.offset + 1
    if (result.locations.length === hits.length) {
      locationsRef.current = result.locations
      setLocations(result.locations)
      setStatus('ready')
      setCurrent(0)
      // 清除上一次标记后定位首处。
      if (markedRef.current !== null) {
        clearTranslationHit(markedRef.current)
        markedRef.current = null
      }
      jumpTo(0, result.locations)
      return
    }
    if (renderedEnough || attemptsRef.current >= 4) {
      // 正文已渲染但命中无法全部定位 → 原文已变化（诚实降级，不跳错）
      setStatus('degraded')
      return
    }
    setStatus('pending') // 尚未渲染完，等待重试
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  // N146：切到 双语/仅译文 后 overlay 才由 ReaderTranslation 注入——
  // 重新定位一次（带重试），拿到「命中块 → 配对译文」关系。
  useEffect(() => {
    if (viewMode === 'original' || hits === null || hits.length === 0) return
    attemptsRef.current = 0
    setStatus('pending')
    attempt()
    const timers = [window.setTimeout(attempt, 350), window.setTimeout(attempt, 1200)]
    return () => {
      for (const t of timers) window.clearTimeout(t)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewMode])

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

  const currentLocation = locations[current] ?? null
  // N146：当前命中带配对译文 → 双语上下文（原文 + 译文片段并列）。
  const sourceSnippet =
    currentLocation?.block !== null && currentLocation?.block !== undefined
      ? hitSnippet(
          currentLocation.block.textContent ?? '',
          currentLocation.blockOffset,
          hits[current]?.term.length ?? 0,
        )
      : null
  const translatedText =
    currentLocation?.translation !== null && currentLocation?.translation !== undefined
      ? (currentLocation.translation.textContent ?? '')
      : null
  const dual =
    viewMode !== 'original' &&
    sourceSnippet !== null &&
    translatedText !== null &&
    translatedText !== ''

  return (
    <div data-lumi-search-hits="" className="absolute left-1/2 top-3 z-10 flex -translate-x-1/2 flex-col items-center gap-1.5">
      <span className="inline-flex items-center gap-1 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] px-2.5 py-1 text-xs text-[var(--lumi-text-secondary)] shadow-[var(--lumi-shadow-popover)]">
        <Crosshair aria-hidden className="size-3.5" />
        命中 {hits.length} 处
        <button
          type="button"
          aria-label="下一处命中"
          onClick={() => {
            const next = (current + 1) % locationsRef.current.length
            setCurrent(next)
            jumpTo(next)
          }}
          className="ms-1 rounded-full px-1.5 py-0.5 font-medium text-[var(--lumi-accent-text)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        >
          下一处
        </button>
      </span>
      {dual && (
        <div
          data-testid="dual-hit-context"
          className="max-w-[min(36rem,90vw)] rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] p-2.5 text-xs leading-relaxed shadow-[var(--lumi-shadow-popover)]"
        >
          <p className="flex items-center gap-1 font-medium text-[var(--lumi-text-tertiary)]">
            <Languages aria-hidden className="size-3.5" />
            双语命中
          </p>
          <p className="mt-1 text-[var(--lumi-text-secondary)]">
            <span className="me-1 font-medium text-[var(--lumi-text-tertiary)]">原文</span>
            {sourceSnippet.clippedStart && '…'}
            <mark className="rounded-[2px] bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]">
              {sourceSnippet.term}
            </mark>
            {sourceSnippet.after}
            {sourceSnippet.clippedEnd && '…'}
          </p>
          <p className="mt-1 text-[var(--lumi-text-secondary)]">
            <span className="me-1 font-medium text-[var(--lumi-text-tertiary)]">译文</span>
            <mark className="rounded-[2px] bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]">
              {translatedText.slice(0, 80)}
            </mark>
            {translatedText.length > 80 && '…'}
          </p>
        </div>
      )}
    </div>
  )
}
