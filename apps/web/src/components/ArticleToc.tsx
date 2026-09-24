/** ArticleToc — 正文目录（pool #03）：内联折叠面板，长文快速跳转。
 *
 * - 内联 <details>：桌面/移动都不遮挡正文（区别于浮层目录），键盘
 *   可达（summary 原生焦点 + Enter 切换），无 z-index/滚动锁问题；
 * - 点击目录项 → scrollIntoView 定位到注入的标题 id（见
 *   lib/article-toc.ts：id 由清洗后 HTML 派生，重复标题去重）；
 * - 少于 2 个标题时不渲染（单标题文章无需目录，也不提供章节模式）。
 *
 * N051 章节化阅读：
 * - 目录头部的「章节模式」开关（toc.length ≥ 2 才有，天然满足）；
 * - 章节模式下点击目录项 = 只显示该标题的章节（lib/article-chapters
 *   按 toc- id 划分；隐藏用 .lumi-chapter-hidden，原文档顺序/链接不动，
 *   退出完整还原 + 恢复进入前的滚动位置）；
 * - 浮动「章节导航」条：上一章 / 下一章 / 退出章节（44px 触控目标，
 *   键盘可达，Escape 也可退出）；
 * - 段落深链（?para= 定位）在章节模式下仍有效：ArticleContent 定位
 *   成功后派发 lumi:para-navigate，此处自动切到包含该段落的章节。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, ListTree, X } from 'lucide-react'
import type { TocEntry } from '../lib/article-toc'
import {
  applyChapterVisibility,
  containingChapterId,
  findChapterSection,
  notifyChapterChange,
} from '../lib/article-chapters'

/** ArticleContent 定位段落成功后派发（detail.element = 目标块）。 */
const PARA_NAVIGATE_EVENT = 'lumi:para-navigate'

function findArticleContainer(root: HTMLElement | null): HTMLElement | null {
  const article = root?.closest('.lumi-reader-article')
  return article?.querySelector<HTMLElement>('.article-content') ?? null
}

function findScrollContainer(root: HTMLElement | null): HTMLElement | null {
  return root?.closest('.lumi-reader-scroll') ?? null
}

/** F074：目录「当前章节」滚动跟随高亮的跟随线偏移（视口顶往下 96px，
 * 与 Reader 位置保存锚线（80px）同一量级；标题越过该线即成为当前章）。 */
const TOC_FOLLOW_LINE_PX = 96

export function ArticleToc({ toc }: { toc: TocEntry[] }) {
  const rootRef = useRef<HTMLDetailsElement | null>(null)
  const [chapterMode, setChapterMode] = useState(false)
  const [activeId, setActiveId] = useState<string | null>(null)
  const savedScrollRef = useRef<number | null>(null)
  // F074：滚动跟随的当前章节（非章节模式下高亮目录项；章节模式的
  // activeId 优先——两者语义不同，不互相覆盖）。
  const [followId, setFollowId] = useState<string | null>(null)

  const activeIndex = activeId === null ? -1 : toc.findIndex((entry) => entry.id === activeId)

  const enterChapter = useCallback(
    (headingId: string) => {
      const root = rootRef.current
      const content = findArticleContainer(root)
      const scroller = findScrollContainer(root)
      if (content === null) return
      // 诚实降级：正文改版找不到该标题 → 不隐藏任何块（保持全文）。
      if (findChapterSection(content, headingId) === null) return
      if (savedScrollRef.current === null) {
        savedScrollRef.current = scroller?.scrollTop ?? null
      }
      applyChapterVisibility(content, headingId)
      setActiveId(headingId)
      if (scroller !== null) scroller.scrollTop = 0
      notifyChapterChange()
    },
    [],
  )

  const exitChapter = useCallback(() => {
    const root = rootRef.current
    const content = findArticleContainer(root)
    const scroller = findScrollContainer(root)
    if (content !== null) applyChapterVisibility(content, null)
    setActiveId(null)
    setChapterMode(false)
    const saved = savedScrollRef.current
    if (scroller !== null && saved !== null) scroller.scrollTop = saved
    savedScrollRef.current = null
    notifyChapterChange()
  }, [])

  // 章节模式开着但正文换血（换文章 = Reader 按 entryRef 重挂载，本组件
  // 随之卸载）；此处兜底：卸载时若仍有隐藏标记则还原（容器节点在挂载时
  // 捕获，避免卸载后 ref 置空拿不到）。
  useEffect(() => {
    const content = findArticleContainer(rootRef.current)
    return () => {
      if (content !== null) applyChapterVisibility(content, null)
    }
  }, [])

  // 段落深链（?para=）：章节模式下自动切到包含目标段落的章节。
  useEffect(() => {
    if (!chapterMode) return
    const onParaNavigate = (event: Event) => {
      const element = (event as CustomEvent).detail?.element
      if (!(element instanceof Element)) return
      const content = findArticleContainer(rootRef.current)
      if (content === null || element.parentElement !== content) return
      const chapterId = containingChapterId(content, element)
      if (chapterId !== null && chapterId !== activeId) enterChapter(chapterId)
    }
    document.addEventListener(PARA_NAVIGATE_EVENT, onParaNavigate)
    return () => document.removeEventListener(PARA_NAVIGATE_EVENT, onParaNavigate)
  }, [chapterMode, activeId, enterChapter])

  // Escape 退出章节（浮动条按钮外的键盘路径）。
  useEffect(() => {
    if (activeId === null) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') exitChapter()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [activeId, exitChapter])

  // F074：滚动跟随高亮（非章节模式）。rAF 节流的 scroll 监听：当前章 =
  // 越过跟随线的最后一个标题；滚到底强制最后一章（短尾章不悬空）。
  // 章节模式 / 目录项点击（activeId）激活期间暂停跟随，退出自动恢复。
  useEffect(() => {
    if (chapterMode || activeId !== null) {
      setFollowId(null)
      return
    }
    const scroller = findScrollContainer(rootRef.current)
    if (scroller === null) return
    const headings = toc
      .map((entry) => document.getElementById(entry.id))
      .filter((el): el is HTMLElement => el !== null)
    if (headings.length === 0) return
    let raf = 0
    const update = () => {
      raf = 0
      const line = scroller.getBoundingClientRect().top + TOC_FOLLOW_LINE_PX
      let current: string | null = null
      for (let i = 0; i < headings.length; i += 1) {
        if (headings[i]!.getBoundingClientRect().top <= line) current = toc[i]!.id
        else break
      }
      const atBottom =
        scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 2
      if (atBottom) current = toc[toc.length - 1]!.id
      setFollowId((prev) => (prev === current ? prev : current))
    }
    const onScroll = () => {
      if (raf !== 0) return
      raf = requestAnimationFrame(update)
    }
    update()
    scroller.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      scroller.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
      if (raf !== 0) cancelAnimationFrame(raf)
    }
  }, [chapterMode, activeId, toc])

  if (toc.length < 2) return null

  const activeEntry = activeIndex >= 0 ? toc[activeIndex] : null
  // F074：目录高亮 id——章节模式用 activeId（用户进入的章节），否则用
  // 滚动跟随 followId；aria-current 与视觉样式共用同一判定。
  const highlightId = activeId ?? (chapterMode ? null : followId)

  return (
    <>
      <details
        ref={rootRef}
        className="article-toc mb-4 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3.5 py-2.5"
      >
        <summary className="flex cursor-pointer select-none items-center justify-between gap-2 text-sm font-medium text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]">
          <span>目录（{toc.length}）</span>
          <button
            type="button"
            aria-pressed={chapterMode}
            data-lumi-chapter-toggle=""
            onClick={(event) => {
              // 按钮不触发 details 折叠；再次点击开关 = 关闭并退出章节
              event.preventDefault()
              event.stopPropagation()
              if (chapterMode || activeId !== null) {
                exitChapter()
              } else {
                setChapterMode(true)
              }
            }}
            className={cxChapterToggle(chapterMode)}
          >
            <ListTree aria-hidden className="size-3.5" />
            章节模式
          </button>
        </summary>
        <ul className="mt-2 flex flex-col gap-0.5 border-t border-[var(--lumi-border)] pt-2">
          {toc.map((entry) => (
            <li
              key={entry.id}
              style={{ paddingInlineStart: `${(entry.level - 2) * 0.875}rem` }}
            >
              <button
                type="button"
                aria-current={entry.id === highlightId ? 'true' : undefined}
                data-lumi-toc-follow={entry.id === followId && activeId === null ? 'true' : undefined}
                onClick={() => {
                  if (chapterMode) {
                    enterChapter(entry.id)
                    return
                  }
                  document
                    .getElementById(entry.id)
                    ?.scrollIntoView({ block: 'start', behavior: 'smooth' })
                }}
                className={
                  'w-full truncate rounded-[var(--lumi-radius-sm)] py-1 text-left text-[13px] transition-colors duration-[var(--lumi-motion-fast)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)] ' +
                  (entry.id === highlightId
                    ? 'font-medium text-[var(--lumi-accent-text)]'
                    : 'text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-accent-text)]')
                }
              >
                {entry.text}
              </button>
            </li>
          ))}
        </ul>
      </details>
      {/* 浮动章节导航（进入章节后出现；44px 触控目标 + 键盘可达） */}
      {activeEntry !== null && (
        <div
          data-lumi-chapter-nav=""
          className="fixed inset-x-3 bottom-4 z-30 mx-auto flex max-w-md items-center justify-between gap-1.5 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] p-1.5 shadow-[var(--lumi-shadow-popover)] max-lg:bottom-[max(1rem,var(--safe-bottom))]"
          role="navigation"
          aria-label="章节导航"
        >
          <button
            type="button"
            aria-label="上一章"
            data-lumi-chapter-prev=""
            disabled={activeIndex <= 0}
            onClick={() => enterChapter(toc[activeIndex - 1].id)}
            className="flex min-h-11 min-w-11 items-center justify-center rounded-full text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] disabled:cursor-default disabled:opacity-40 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            <ChevronLeft aria-hidden className="size-5" />
          </button>
          <span
            aria-live="polite"
            data-lumi-chapter-title=""
            className="min-w-0 flex-1 truncate text-center text-xs text-[var(--lumi-text-secondary)]"
          >
            第 {activeIndex + 1}/{toc.length} 章 · {activeEntry.text}
          </span>
          <button
            type="button"
            aria-label="下一章"
            data-lumi-chapter-next=""
            disabled={activeIndex >= toc.length - 1}
            onClick={() => enterChapter(toc[activeIndex + 1].id)}
            className="flex min-h-11 min-w-11 items-center justify-center rounded-full text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] disabled:cursor-default disabled:opacity-40 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            <ChevronRight aria-hidden className="size-5" />
          </button>
          <button
            type="button"
            aria-label="退出章节"
            data-lumi-chapter-exit=""
            onClick={exitChapter}
            className="flex min-h-11 min-w-11 items-center justify-center rounded-full text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            <X aria-hidden className="size-5" />
          </button>
        </div>
      )}
    </>
  )
}

function cxChapterToggle(active: boolean): string {
  return (
    'flex shrink-0 items-center gap-1 rounded-[var(--lumi-radius-full)] px-2 py-1 text-xs transition-colors duration-[var(--lumi-motion-fast)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)] ' +
    (active
      ? 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]'
      : 'bg-[var(--lumi-surface-hover)] text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)]')
  )
}

export default ArticleToc
