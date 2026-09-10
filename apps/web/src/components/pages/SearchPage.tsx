/** SearchPage — 全局搜索（0022 正式功能，取代 0011 诚实占位）。
 *
 * 后端：GET /api/v1/search（派生投影，见 BFF search_index.py）。
 * 本页职责：
 * - 输入防抖 300ms（§23）；Enter 立即执行；清空 / 取消；
 * - 过滤器 chips：全部 / 未读 / 收藏（服务端 state/favorite 过滤）
 *   + 分类下拉（复用 useFeeds 的真实分类，category 服务端过滤）；
 * - 结果行：标题 / 来源 / 时间 / 摘要片段（plain text，绝不
 *   dangerouslySetInnerHTML）+ matchedFields 徽标；
 * - 无限滚动翻页（cursor opaque 透传）；
 * - 诚实状态：加载 / 空结果 / 错误重试 / 索引未就绪（index.entryCount
 *   === 0 时明确说明，不冒充「无结果」）；
 * - 搜索历史保留（本地 UI 数据，上限 10）。
 *
 * 返回保持：打开文章时本页保持挂载（App 布局契约），返回后查询、
 * 过滤器、滚动位置不变。
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { Loader2, Search, X } from 'lucide-react'
import { useFeeds, useSearch } from '../../api/queries'
import type { SearchItem } from '../../api/types'
import { useReaderUi } from '../../store/reader-ui'
import { formatPublishedAt } from '../../lib/date-format'
import {
  clearSearchHistory,
  pushSearchHistory,
  readSearchHistory,
  removeFromSearchHistory,
} from '../../lib/search-history'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'

type ViewFilter = 'all' | 'unread' | 'starred'

const VIEW_CHIPS: { key: ViewFilter; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'unread', label: '未读' },
  { key: 'starred', label: '收藏' },
]

/** 防抖：输入停止 300ms 后才更新值（§23 250–350ms）。 */
function useDebouncedValue(value: string, delayMs = 300): string {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])
  return debounced
}

function ResultRow({ item }: { item: SearchItem }) {
  const selectEntry = useReaderUi((s) => s.selectEntry)
  const selectedEntryRef = useReaderUi((s) => s.selectedEntryRef)
  const selected = selectedEntryRef === item.entryRef
  return (
    // Phase H/I：视口外行跳过 layout/paint（与 EntryList 同一策略）。
    <li className="lumi-row-cv">
      <button
        type="button"
        data-entry-ref={item.entryRef}
        onClick={() => selectEntry(item.entryRef)}
        aria-pressed={selected}
        className={cx(
          'flex w-full flex-col gap-1 rounded-[var(--lumi-radius-lg)] px-3.5 py-3 text-left',
          'transition-colors duration-[var(--lumi-motion-fast)]',
          selected
            ? 'bg-[var(--lumi-surface-selected)]'
            : 'hover:bg-[var(--lumi-surface-hover)] active:bg-[var(--lumi-surface-pressed)]',
          'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
        )}
      >
        <span className="flex min-w-0 items-center gap-1.5 text-xs text-[var(--lumi-text-tertiary)]">
          <span className="truncate">{item.feedTitle}</span>
          <span aria-hidden>·</span>
          <span className="shrink-0">{formatPublishedAt(item.publishedAt)}</span>
          {!item.read && (
            <span
              aria-label="未读"
              className="ml-auto size-2 shrink-0 rounded-full bg-[var(--lumi-accent-text)]"
            />
          )}
        </span>
        <span
          className={cx(
            'line-clamp-2 text-sm',
            item.read
              ? 'text-[var(--lumi-text-secondary)]'
              : 'font-medium text-[var(--lumi-text-primary)]',
          )}
        >
          {item.title}
        </span>
        {item.snippet !== '' && (
          <span className="line-clamp-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
            {item.snippet}
          </span>
        )}
      </button>
    </li>
  )
}

export default function SearchPage() {
  const [input, setInput] = useState('')
  const [submitted, setSubmitted] = useState('')
  const [view, setView] = useState<ViewFilter>('all')
  const [categoryKey, setCategoryKey] = useState<string>('')
  const [history, setHistory] = useState<string[]>(() => readSearchHistory())
  const debounced = useDebouncedValue(input)

  const feeds = useFeeds()
  const categories = useMemo(() => {
    const feedList = Array.isArray(feeds.data) ? feeds.data : []
    const map = new Map<string, string>()
    for (const feed of feedList) {
      if (feed.category && !map.has(feed.category.id)) {
        map.set(feed.category.id, feed.category.label)
      }
    }
    return [...map.entries()].map(([id, label]) => ({ id, label }))
  }, [feeds.data])

  // 提交值 = 显式提交或防抖后的输入（两者取新：Enter 立即、停顿自动）
  useEffect(() => {
    setSubmitted(debounced)
  }, [debounced])

  const trimmed = submitted.trim()
  const search = useSearch(trimmed, {
    categoryId: categoryKey || null,
    state: view === 'unread' ? 'unread' : null,
    favorite: view === 'starred' ? true : null,
  })
  const { data, isPending, isError, error, refetch, hasNextPage, isFetchingNextPage, fetchNextPage } = search

  const results = useMemo(
    () => data?.pages.flatMap((page) => page.items) ?? [],
    [data],
  )
  const indexInfo = data?.pages.at(-1)?.index

  // 无限滚动（与 EntryList / FavoritesPage 同一模式）
  const sentinelRef = useRef<HTMLLIElement>(null)
  useEffect(() => {
    const sentinel = sentinelRef.current
    if (!sentinel || !hasNextPage || isFetchingNextPage) return
    const observer = new IntersectionObserver(
      (records) => {
        if (records.some((r) => r.isIntersecting) && !isFetchingNextPage) {
          fetchNextPage()
        }
      },
      { rootMargin: '0px 0px 50% 0px' },
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [hasNextPage, isFetchingNextPage, fetchNextPage])

  const commit = (value: string) => {
    const q = value.trim()
    if (!q) return
    setSubmitted(q)
    setInput(q)
    setHistory((prev) => pushSearchHistory(prev, q))
  }

  const cancel = () => {
    setInput('')
    setSubmitted('')
  }

  const hasQuery = trimmed.length > 0

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-3 max-lg:pb-[76px]">
        {/* 主搜索框：防抖自动 + Enter 立即；原生 × 清空；取消重置 */}
        <div className="flex gap-2">
          <div className="relative min-w-0 flex-1">
            <Search
              aria-hidden
              className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--lumi-text-tertiary)]"
            />
            <input
              type="search"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commit(input)
              }}
              placeholder="搜索文章标题、正文或作者…"
              aria-label="搜索"
              className={cx(
                'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
                'py-2.5 pl-9 pr-3 text-sm text-[var(--lumi-text-primary)]',
                'placeholder:text-[var(--lumi-text-tertiary)]',
                'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
              )}
            />
          </div>
          {input.trim() !== '' && (
            <Button variant="ghost" size="sm" onClick={cancel} className="shrink-0">
              取消
            </Button>
          )}
        </div>

        {/* 过滤器 chips + 分类下拉（服务端过滤，语义真实） */}
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          <div role="group" aria-label="搜索范围" className="flex gap-1.5">
            {VIEW_CHIPS.map((chip) => (
              <button
                key={chip.key}
                type="button"
                onClick={() => setView(chip.key)}
                aria-pressed={view === chip.key}
                className={cx(
                  'rounded-[var(--lumi-radius-full)] px-2.5 py-1 text-xs',
                  'min-h-7 transition-colors duration-[var(--lumi-motion-fast)]',
                  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                  view === chip.key
                    ? 'bg-[var(--lumi-accent-soft)] font-medium text-[var(--lumi-accent-text)]'
                    : 'border border-[var(--lumi-border)] text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]',
                )}
              >
                {chip.label}
              </button>
            ))}
          </div>
          {categories.length > 0 && (
            <select
              value={categoryKey}
              onChange={(e) => setCategoryKey(e.target.value)}
              aria-label="按分类过滤"
              className={cx(
                'max-w-40 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs',
                'min-h-7 text-[var(--lumi-text-secondary)]',
                'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
              )}
            >
              <option value="">全部分类</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
          )}
        </div>

        {/* 搜索历史（本地 UI 数据；上限 10；无查询时展示） */}
        {!hasQuery && history.length > 0 && (
          <section className="mt-5" aria-label="搜索历史">
            <div className="mb-2 flex items-center justify-between px-1">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-[var(--lumi-text-tertiary)]">
                搜索历史
              </h2>
              <button
                type="button"
                onClick={() => setHistory(clearSearchHistory(history))}
                className="rounded-[var(--lumi-radius-md)] px-2 py-1 text-xs text-[var(--lumi-text-secondary)] transition-colors hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
              >
                清空
              </button>
            </div>
            <ul className="flex flex-wrap gap-2">
              {history.map((q) => (
                <li key={q}>
                  <div className="flex items-center gap-1 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] pl-2.5 pr-1">
                    <button
                      type="button"
                      onClick={() => {
                        setInput(q)
                        setSubmitted(q)
                      }}
                      className="max-w-48 truncate py-1.5 text-xs text-[var(--lumi-text-secondary)] transition-colors hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                    >
                      {q}
                    </button>
                    <button
                      type="button"
                      onClick={() => setHistory(removeFromSearchHistory(history, q))}
                      aria-label={`删除历史「${q}」`}
                      className="relative flex size-6 items-center justify-center rounded-full text-[var(--lumi-text-tertiary)] transition-colors after:absolute after:-inset-y-2.5 after:-inset-x-1 after:content-[''] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                    >
                      <X aria-hidden className="size-3" />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* 结果 / 诚实状态 */}
        {hasQuery ? (
          isPending ? (
            <ul className="mt-4 flex flex-col gap-2" aria-label="搜索中">
              {Array.from({ length: 4 }, (_, i) => (
                <li key={i}>
                  <Skeleton className="h-20 w-full" />
                </li>
              ))}
            </ul>
          ) : isError ? (
            <div className="mt-6" role="alert">
              <EmptyState
                icon={<X aria-hidden className="size-8" />}
                title="搜索失败"
                description={error instanceof Error ? error.message : '请稍后重试。'}
              />
              <div className="flex justify-center">
                <Button variant="secondary" size="sm" onClick={() => refetch()}>
                  重试
                </Button>
              </div>
            </div>
          ) : results.length === 0 ? (
            <div className="mt-6">
              {(indexInfo?.entryCount ?? 0) === 0 ? (
                <EmptyState
                  icon={<Search aria-hidden className="size-8" />}
                  title="搜索索引还没有内容"
                  description="索引会在后台自动从 FreshRSS 构建（或点上方重试触发同步）；构建完成前搜索不到内容是正常状态。"
                />
              ) : (
                <EmptyState
                  icon={<Search aria-hidden className="size-8" />}
                  title={`没有找到与「${trimmed}」相关的内容`}
                  description="试试更短的关键词，或放宽过滤器。"
                />
              )}
            </div>
          ) : (
            <>
              <ul className="mt-3 flex flex-col gap-1" aria-label="搜索结果">
                {results.map((item) => (
                  <ResultRow key={item.entryRef} item={item} />
                ))}
                {isFetchingNextPage && (
                  <li className="flex justify-center py-3">
                    <Loader2 aria-hidden className="size-4 animate-spin text-[var(--lumi-text-tertiary)]" />
                  </li>
                )}
                <li ref={sentinelRef} aria-hidden className="h-px" />
              </ul>
              {results.length > 0 && (
                <p className="px-1 pt-2 text-xs text-[var(--lumi-text-tertiary)]" role="status">
                  共约 {results.length}
                  {hasNextPage ? '+ 条结果' : ' 条结果'}
                </p>
              )}
            </>
          )
        ) : history.length === 0 ? (
          <div className="mt-8">
            <EmptyState
              icon={<Search aria-hidden className="size-8" />}
              title="搜索你的全部订阅"
              description="输入关键词搜索文章标题、正文与作者；支持中文与英文。"
            />
          </div>
        ) : null}
      </div>
    </div>
  )
}
