/** P0-2（2026-09-18 移动端专项）：正文读到底自动标为已读。
 *
 * 与两个既有行为严格区分（不得混淆）：
 * - 「列表划过标为已读」（scrollMarkUnread，EntryList 的列表 observer）；
 * - 「阅读位置保存/恢复」（reading-position，只记滚动，绝不写已读）。
 * 本模块是第三个行为：Reader 正文容器的末尾哨兵 + 主动阅读推进 +
 * 前台 + 稳定停留 → 恰好一次 set 语义的 read:true。
 *
 * 设计阈值（写入测试，改动需同步测试）：
 * - DWELL_MS                末尾持续可见的稳定停留窗口；
 * - MIN_PROGRESS_PX         本次访问内主动向下推进量下限（程序恢复位置/
 *                           图片加载位移/自动滚屏不算主动阅读；上滑不累计）；
 * - PROGRAMMATIC_WINDOW_MS  恢复位置/自动滚屏后滚动事件的豁免窗口；
 * - SHORT_ARTICLE_PX        正文可滚动余量小于该值视为短文 → 不自动判定，
 *                           由「读完了」按钮提供明确的主动确认。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

export const FINISH_READ_DWELL_MS = 1000
export const FINISH_READ_MIN_PROGRESS_PX = 40
export const FINISH_READ_PROGRAMMATIC_WINDOW_MS = 200
export const FINISH_READ_SHORT_ARTICLE_PX = 24

/** 纯判定：正文是否可滚动（短文 = 无有效滚动空间）。 */
export function isArticleScrollable(
  scrollHeight: number,
  clientHeight: number,
): boolean {
  return scrollHeight - clientHeight > FINISH_READ_SHORT_ARTICLE_PX
}

/** 纯计算：达到「主动推进」所需的下限量。长文用固定值；滚动余量很小
 * 的文章按余量一半（且至少 8px）取值，避免微小余量永远无法达标。 */
export function requiredProgressFor(rangePx: number): number {
  if (rangePx <= 0) return Number.POSITIVE_INFINITY
  return Math.max(8, Math.min(FINISH_READ_MIN_PROGRESS_PX, rangePx * 0.5))
}

export interface FinishReadConditions {
  enabled: boolean
  read: boolean
  suspended: boolean
  endVisible: boolean
  pageVisible: boolean
  /** 本次访问累计向下推进量（px）。 */
  progressPx: number
  /** 当前文章的滚动余量（px），用于派生推进量阈值。 */
  scrollRangePx: number
}

/** 纯决策：是否满足开始「末尾稳定停留」计时的全部条件（无 DOM）。
 * 计时起点与触发点各核验一次。 */
export function shouldDwell(conditions: FinishReadConditions): boolean {
  if (
    !conditions.enabled ||
    conditions.read ||
    conditions.suspended ||
    !conditions.endVisible ||
    !conditions.pageVisible
  ) {
    return false
  }
  if (!isArticleScrollable(conditions.scrollRangePx, 0)) {
    return false
  }
  return conditions.progressPx >= requiredProgressFor(conditions.scrollRangePx)
}

export interface UseFinishReadOptions {
  /** 设置开关（readerAutoMarkRead）。 */
  enabled: boolean
  /** 当前文章 ref；null = 无正文（不发判定）。 */
  entryRef: string | null
  /** 当前已读状态（来自 detail 缓存的真值）。 */
  read: boolean
  /** 触发标记（Reader 侧接 useEntryStateMutation；set 语义 read:true）。
   * 返回 promise：resolve = 服务端确认；reject = 服务端失败。 */
  markRead: (entryRef: string) => Promise<unknown>
}

export interface FinishReadController {
  /** Reader 滚动容器 ref（必须真正滚动的容器，不混用 window）。
   * hook 在此挂原生 passive scroll 监听（不依赖 React onScroll 绑定）。 */
  setContainer: (node: HTMLDivElement | null) => void
  /** 哨兵元素 ref：挂在正文实际结束处（摘要/AI 对话等面板之前）。 */
  sentinelRef: (node: HTMLElement | null) => void
  /** 程序性滚动（恢复位置/自动滚屏）前调用：豁免随后滚动事件。 */
  noteProgrammaticScroll: () => void
  /** 短文且未读 → 显示「读完了」按钮（主动确认路径）。 */
  needsExplicitConfirm: boolean
  /** 「读完了」按钮点击 → 直接派发（不受推进量/停留限制）。 */
  confirmFinished: () => void
  /** 自动判定失败信息（显示提示 + 重试入口；不误报服务器拒绝）。 */
  autoError: string | null
  /** 重试上一次失败的判定。 */
  retry: () => void
  /** 调试/测试：当前是否处于停留计时中。 */
  isDwelling: boolean
}

/** 会话级暂停集合：手动标为未读 / 撤销自动已读 的文章，本次访问不再
 * 自动判定（模块级——切文章往返不重置；刷新页面重置）。 */
const sessionSuspended = new Set<string>()

export function resetFinishReadSessionForTests(): void {
  sessionSuspended.clear()
}

export function useFinishRead(options: UseFinishReadOptions): FinishReadController {
  const { enabled, entryRef, read, markRead } = options

  // ---- 状态（per-entryRef；切换文章整体重置） ----
  const baselineTopRef = useRef(0)
  const maxTopRef = useRef(0)
  const lastScrollTopRef = useRef(0)
  const programmaticUntilRef = useRef(0)
  const endVisibleRef = useRef(false)
  const scrollRangeRef = useRef(0)
  const dwellTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const dispatchedRef = useRef(false)
  const prevReadRef = useRef(read)
  const entryRefRef = useRef<string | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const sentinelElRef = useRef<HTMLElement | null>(null)
  const observerRef = useRef<IntersectionObserver | null>(null)
  const markReadRef = useRef(markRead)
  markReadRef.current = markRead

  const [isDwelling, setIsDwelling] = useState(false)
  const [isShortArticle, setIsShortArticle] = useState(false)
  const [autoError, setAutoError] = useState<string | null>(null)

  const pageVisible = useCallback(
    () => typeof document === 'undefined' || document.visibilityState === 'visible',
    [],
  )

  const clearDwell = useCallback(() => {
    if (dwellTimerRef.current !== null) {
      clearTimeout(dwellTimerRef.current)
      dwellTimerRef.current = null
    }
    setIsDwelling(false)
  }, [])

  /** 派发一次 read:true。成功 → 终态；失败 → 释放重试（不进已处理集合）。 */
  const dispatch = useCallback(() => {
    const currentRef = entryRefRef.current
    if (currentRef === null || dispatchedRef.current) return
    dispatchedRef.current = true
    clearDwell()
    setAutoError(null)
    markReadRef
      .current(currentRef)
      .then(() => {
        /* 成功：缓存补丁由 mutation 负责；终态不再触发 */
      })
      .catch((error: unknown) => {
        dispatchedRef.current = false
        setAutoError(
          error instanceof Error ? error.message : '自动标记已读失败，可重试。',
        )
      })
  }, [clearDwell])

  /** 评估：条件齐备且未派发 → 起一个 DWELL_MS 计时；任何条件缺失 →
   * 清除计时。IO 回调 / 滚动 / 可见性变化共用。经 ref 间接调用，
   * 保证 observer 构造时捕获的回调永远指向最新实现。 */
  const evaluateRef = useRef<() => void>(() => {})
  const evaluate = useCallback(() => {
    const currentRef = entryRefRef.current
    if (currentRef === null || dispatchedRef.current) {
      clearDwell()
      return
    }
    /** 触发点重建：停留期间 read/enabled 等可能已变化。 */
    const buildConditions = (): FinishReadConditions => ({
      enabled,
      read,
      suspended: sessionSuspended.has(currentRef),
      endVisible: endVisibleRef.current,
      pageVisible: pageVisible(),
      progressPx: maxTopRef.current - baselineTopRef.current,
      scrollRangePx: scrollRangeRef.current,
    })
    if (!shouldDwell(buildConditions())) {
      clearDwell()
      return
    }
    if (dwellTimerRef.current !== null) return // 已在计时中
    setIsDwelling(true)
    dwellTimerRef.current = setTimeout(() => {
      dwellTimerRef.current = null
      // 触发点复核：停留期间条件可能已变化（切文章/后台/已读）。
      if (shouldDwell(buildConditions()) && !dispatchedRef.current) {
        dispatch()
      } else {
        setIsDwelling(false)
      }
    }, FINISH_READ_DWELL_MS)
  }, [enabled, read, pageVisible, clearDwell, dispatch])
  evaluateRef.current = evaluate

  // ---- 手动未读保护（§2.4.9）：read true→false 视为用户明确未读意图 ----
  useEffect(() => {
    if (prevReadRef.current === true && read === false && entryRef !== null) {
      sessionSuspended.add(entryRef)
      dispatchedRef.current = false
      clearDwell()
    }
    prevReadRef.current = read
  }, [read, entryRef, clearDwell])

  // ---- 切换文章：整体重置；推进量以恢复后的位置为基线重新积累 ----
  useEffect(() => {
    if (entryRefRef.current === entryRef) return
    entryRefRef.current = entryRef
    endVisibleRef.current = false
    dispatchedRef.current = false
    prevReadRef.current = read
    setAutoError(null)
    clearDwell()
    const container = containerRef.current
    if (container !== null) {
      scrollRangeRef.current = Math.max(
        0,
        container.scrollHeight - container.clientHeight,
      )
      baselineTopRef.current = container.scrollTop
      maxTopRef.current = container.scrollTop
      lastScrollTopRef.current = container.scrollTop
      setIsShortArticle(!isArticleScrollable(container.scrollHeight, container.clientHeight))
    } else {
      scrollRangeRef.current = 0
      setIsShortArticle(false)
    }
  }, [entryRef, read, clearDwell])

  // ---- 正文渲染完成后重测容器（图片/译文展开使余量变化） ----
  const remeasure = useCallback(() => {
    const container = containerRef.current
    if (container === null) return
    scrollRangeRef.current = Math.max(
      0,
      container.scrollHeight - container.clientHeight,
    )
    setIsShortArticle(!isArticleScrollable(container.scrollHeight, container.clientHeight))
  }, [])

  // ---- 哨兵 observer：以 Reader 滚动容器为 root（不混用 window） ----
  const attachObserver = useCallback(() => {
    observerRef.current?.disconnect()
    observerRef.current = null
    // 能力检测：无 IntersectionObserver 的环境（jsdom/极老浏览器）静默
    // 降级——自动判定不可用（endVisible 永为 false，绝不误派发）。
    if (typeof IntersectionObserver === 'undefined') return
    const el = sentinelElRef.current
    const container = containerRef.current
    if (el === null || container === null) return
    const observer = new IntersectionObserver(
      (records) => {
        for (const r of records) endVisibleRef.current = r.isIntersecting
        evaluateRef.current()
      },
      { root: container, threshold: 0 },
    )
    observer.observe(el)
    observerRef.current = observer
  }, [])

  const sentinelRef = useCallback(
    (node: HTMLElement | null) => {
      sentinelElRef.current = node
      if (node === null) endVisibleRef.current = false
      remeasure()
      attachObserver()
    },
    [attachObserver, remeasure],
  )

  // ---- 滚动事件：主动向下推进（程序性窗口内豁免；上滑不累计） ----
  /** 原生 passive 监听（setContainer 挂载/替换容器时接线）。 */
  const onScroll = useCallback(() => {
    const container = containerRef.current
    if (container === null) return
    // 每次滚动重测余量：图片延迟加载/译文展开/字号变化后，短文可能
    // 变长文（反之亦然）；scrollHeight 读取在滚动帧内通常无强制重排。
    remeasure()
    const top = container.scrollTop
    const now = Date.now()
    if (now >= programmaticUntilRef.current) {
      if (top > maxTopRef.current) maxTopRef.current = top
    }
    lastScrollTopRef.current = top
    evaluateRef.current()
  }, [remeasure])

  const setContainer = useCallback(
    (node: HTMLDivElement | null) => {
      const previous = containerRef.current
      if (previous !== null) previous.removeEventListener('scroll', onScroll)
      containerRef.current = node
      if (node !== null) {
        node.addEventListener('scroll', onScroll, { passive: true })
        remeasure()
        baselineTopRef.current = node.scrollTop
        maxTopRef.current = node.scrollTop
        lastScrollTopRef.current = node.scrollTop
        attachObserver()
      }
    },
    [attachObserver, remeasure, onScroll],
  )

  const noteProgrammaticScroll = useCallback(() => {
    programmaticUntilRef.current = Date.now() + FINISH_READ_PROGRAMMATIC_WINDOW_MS
  }, [])

  // ---- 前台/后台：后台取消计时；回前台重新评估（新停留窗口） ----
  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') clearDwell()
      else evaluateRef.current()
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
  }, [clearDwell])

  // ---- 卸载清理（observer / scroll listener / timer） ----
  useEffect(
    () => () => {
      observerRef.current?.disconnect()
      observerRef.current = null
      containerRef.current?.removeEventListener('scroll', onScroll)
      if (dwellTimerRef.current !== null) clearTimeout(dwellTimerRef.current)
    },
    [onScroll],
  )

  const confirmFinished = useCallback(() => {
    if (entryRefRef.current === null || dispatchedRef.current) return
    dispatch()
  }, [dispatch])

  const retry = useCallback(() => {
    if (entryRefRef.current === null || autoError === null) return
    setAutoError(null)
    dispatch()
  }, [autoError, dispatch])

  return useMemo(
    () => ({
      setContainer,
      sentinelRef,
      noteProgrammaticScroll,
      needsExplicitConfirm: enabled && isShortArticle && !read && entryRef !== null,
      confirmFinished,
      autoError,
      retry,
      isDwelling,
    }),
    [
      enabled,
      isShortArticle,
      read,
      entryRef,
      confirmFinished,
      autoError,
      retry,
      isDwelling,
      setContainer,
      sentinelRef,
      noteProgrammaticScroll,
    ],
  )
}
