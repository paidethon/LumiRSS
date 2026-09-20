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

import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'
import { useInfiniteQuery, keepPreviousData, useQueryClient } from '@tanstack/react-query'
import { Calendar, GitCompare, Loader2, Rss, Search, SlidersHorizontal, X } from 'lucide-react'
import {
  SEARCH_RESULTS_KEY,
  useCreateSavedSearchViewMutation,
  useDeleteSavedSearchViewMutation,
  useFeeds,
  useSubscriptions,
  useRenameSavedSearchViewMutation,
  useSavedSearchViews,
  useSearch,
} from '../../api/queries'
import { mergeUnique } from '../../lib/merge-unique'
import {
  EMPTY_ADVANCED_FILTER,
  hasAdvancedText,
  isAdvancedSearchActive,
  quickRange,
  searchEntriesAdvanced,
  describeAdvancedQuery,
  EMPTY_BUILDER_FILTERS,
  hasBuilderFilters,
  type AdvancedTextFilter,
  type BuilderFilters,
  type QuickDateRangeKind,
} from '../../lib/search-advanced'
import { HighlightText, splitTerms } from '../../lib/highlight-text'
import type { LibrarySearchItem } from '../../api/client'
import type { SavedSearchView, SearchItem } from '../../api/types'
import { useReaderUi } from '../../store/reader-ui'
import { useAppSettings } from '../../store/app-settings'
import { useSearchState } from '../../store/search-state'
import { resolveAndOpen } from '../../lib/open-item'
import { stashSearchHits } from '../../lib/search-hit-locate'
import { MatchExplainBadges } from '../MatchExplain'
import { ViewFeedTokenDialog } from '../ViewFeedTokenDialog'
import { SearchExportDialog } from '../SearchExportDialog'
import { SynonymsControls, readExpandSynonyms } from '../SynonymsControls'
import { isHistoryPaused } from '../../lib/search-history'
import { ViewCompareDialog } from '../ViewCompareDialog'
import { dateTimeFormatter, formatListTime } from '../../lib/date-format'
import { SourceGlyph, SourceLabel } from '../../lib/source-meta'
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

const AuthorAggregatesPanelLazy = lazy(() => import('../AuthorAggregatesPanel'))

type ViewFilter = 'all' | 'unread' | 'starred'

const VIEW_CHIPS: { key: ViewFilter; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'unread', label: '未读' },
  { key: 'starred', label: '收藏' },
]

/** F27 快捷日期范围（label 同时作为已应用 chip 文案）。 */
const QUICK_RANGE_LABELS: Record<QuickDateRangeKind, string> = {
  today: '今天',
  '7d': '近 7 天',
  '30d': '近 30 天',
}

/** F28 命中高亮的 <mark> 样式（语义 token；不用硬编码颜色）。 */
const HIGHLIGHT_MARK_CLS =
  'rounded-[2px] bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]'

/** 防抖：输入停止 300ms 后才更新值（§23 250–350ms）。 */
function useDebouncedValue(value: string, delayMs = 300): string {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])
  return debounced
}

// ---- 库分组（phase2 G6：/search 响应的 additive library 腿） ----

const LIBRARY_KIND_LABELS: Record<string, string> = {
  bookmark: '书签',
  clip: '剪藏',
  obsidian_note: '笔记',
  snapshot: '快照',
  api_item: '收件',
}

function libraryKindLabel(kind: string): string {
  return LIBRARY_KIND_LABELS[kind] ?? kind
}

/** ISO 时间戳 → 相对时间（库结果行的 updatedAt）；无效回退绝对时间。 */
function formatRelative(iso: string | null | undefined): string {
  if (iso === null || iso === undefined || iso === '') return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  const minutes = Math.floor((Date.now() - date.getTime()) / 60_000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return dateTimeFormatter.format(date)
}

/** 库搜索结果行：标题按钮（resolve → 按 kind 路由：Reader / 外链 /
 * 剪藏 / 快照沙箱页 / Obsidian）。wave 2（P0-02「一切皆可打开」）：
 * 行不再是惰性文本；stale 行禁用打开并显式标注。 */
function LibraryResultRow({ item }: { item: LibrarySearchItem }) {
  const [openError, setOpenError] = useState<string | null>(null)
  const stale = item.stale

  const open = async () => {
    setOpenError(null)
    try {
      const resolved = await resolveAndOpen(item.ref)
      if (resolved === null) {
        setOpenError('打开失败：内容解析请求未成功，请稍后重试。')
      } else if (resolved.stale) {
        setOpenError('内容已失效，无法打开。')
      }
    } catch (error) {
      setOpenError(error instanceof Error ? error.message : '打开失败，请稍后重试。')
    }
  }

  return (
    <li className="flex flex-col gap-1 rounded-[var(--lumi-radius-lg)] px-3.5 py-3">
      <span className="flex min-w-0 items-center gap-2 text-xs text-[var(--lumi-text-tertiary)]">
        <span className="shrink-0 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-1.5 py-0.5 text-[11px]">
          {libraryKindLabel(item.kind)}
        </span>
        {stale && (
          <span className="shrink-0 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[11px]">
            已失效
          </span>
        )}
        <span className="ml-auto shrink-0">{formatRelative(item.updatedAt)}</span>
      </span>
      {stale ? (
        <span className="line-clamp-2 text-sm font-medium text-[var(--lumi-text-secondary)]">
          {item.title}
        </span>
      ) : (
        <button
          type="button"
          onClick={() => void open()}
          className="line-clamp-2 text-left text-sm font-medium text-[var(--lumi-text-primary)] underline-offset-2 transition-colors duration-[var(--lumi-motion-fast)] hover:text-[var(--lumi-accent-text)] hover:underline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        >
          {item.title}
        </button>
      )}
      {item.snippet !== '' && (
        <span className="line-clamp-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          {item.snippet}
        </span>
      )}
      {openError !== null && (
        <span role="alert" className="text-xs text-[var(--lumi-danger)]">
          {openError}
        </span>
      )}
    </li>
  )
}

/** 库搜索结果分组：标题行 / kind 徽标 / snippet（纯文本，不进 HTML）/
 * updatedAt 相对时间；libraryError 时小字诚实提示（库腿失败不影响
 * RSS 结果展示）。items 为空且无 error → 不渲染。 */
function LibraryGroup({
  items,
  error,
}: {
  items: LibrarySearchItem[]
  error: string | null
}) {
  if (items.length === 0 && error === null) return null
  return (
    <section className="mt-5" aria-label="库搜索结果">
      <h3 className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-[var(--lumi-text-tertiary)]">
        库
      </h3>
      {items.length > 0 && (
        <ul className="flex flex-col gap-1">
          {items.map((item) => (
            <LibraryResultRow key={item.ref} item={item} />
          ))}
        </ul>
      )}
      {error !== null && (
        <p role="status" className="px-1 pt-1 text-xs text-[var(--lumi-text-secondary)]">
          库搜索暂不可用：{error}
        </p>
      )}
    </section>
  )
}

/** F28：RSS 结果行（标题与摘要接入安全高亮；terms 来自搜索词分词）。 */
function ResultRow({
  item,
  terms,
  highlightEnabled,
  lastSyncedAt,
  libraryError,
}: {
  item: SearchItem
  terms: string[]
  highlightEnabled: boolean
  lastSyncedAt: string | null
  libraryError: string | null
}) {
  const selectEntry = useReaderUi((s) => s.selectEntry)
  const selectedEntryRef = useReaderUi((s) => s.selectedEntryRef)
  const timeFormat = useAppSettings((s) => s.settings.listTimeFormat)
  const selected = selectedEntryRef === item.entryRef
  return (
    // Phase H/I：视口外行跳过 layout/paint（与 EntryList 同一策略）。
    // P2：来源行与打开按钮平级（来源可点击进入该订阅范围，不嵌套按钮）。
    <li className="lumi-row-cv">
      <div
        data-entry-ref={item.entryRef}
        className={cx(
          'flex w-full flex-col gap-1 rounded-[var(--lumi-radius-lg)] px-3.5 py-3 text-left',
          'transition-colors duration-[var(--lumi-motion-fast)]',
          selected
            ? 'bg-[var(--lumi-surface-selected)]'
            : 'hover:bg-[var(--lumi-surface-hover)] active:bg-[var(--lumi-surface-pressed)]',
        )}
      >
        <div className="flex min-w-0 items-center gap-1.5 text-xs text-[var(--lumi-text-tertiary)]">
          <SourceGlyph name={item.feedTitle} />
          <SourceLabel
            feedTitle={item.feedTitle}
            feedUrl={item.feedUrl}
            className="min-w-0 flex-1 text-left"
          />
          <span className="shrink-0">{formatListTime(item.publishedAt, timeFormat)}</span>
          {!item.read && (
            <span
              aria-label="未读"
              className="ml-1 size-2 shrink-0 rounded-full bg-[var(--lumi-accent-text)]"
            />
          )}
        </div>
        {/* F074：命中解释徽标 +「为什么匹配」popover */}
        {(item.matchedFields?.length ?? 0) > 0 && (
          <MatchExplainBadges
            item={item}
            terms={terms}
            lastSyncedAt={lastSyncedAt}
            libraryError={libraryError}
          />
        )}
        <button
          type="button"
          onClick={() => {
            // F072：打开前暂存正文命中偏移（Reader 定位用）
            const hits = (item as SearchItem & { matchPositions?: { offset: number; term: string }[] | null }).matchPositions
            stashSearchHits(item.entryRef, hits ?? [])
            selectEntry(item.entryRef)
          }}
          aria-pressed={selected}
          className={cx(
            'flex w-full flex-col gap-1 rounded-[var(--lumi-radius-md)] text-left',
            'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
          )}
        >
          <span
            className={cx(
              'line-clamp-2 text-sm',
              item.read
                ? 'text-[var(--lumi-text-secondary)]'
                : 'font-medium text-[var(--lumi-text-primary)]',
            )}
          >
            <HighlightText text={item.title} terms={terms} enabled={highlightEnabled} markClassName={HIGHLIGHT_MARK_CLS} />
          </span>
          {item.snippet !== '' && (
            <span className="line-clamp-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
              <HighlightText text={item.snippet} terms={terms} enabled={highlightEnabled} markClassName={HIGHLIGHT_MARK_CLS} />
            </span>
          )}
        </button>
      </div>
    </li>
  )
}

export default function SearchPage() {
  // P1.3：搜索词/筛选提升到会话 store（浏览器返回/侧滑可恢复；桌面与
  // 移动挂载点共享同一状态）。输入防抖仍是本地行为。
  const input = useSearchState((s) => s.q)
  const setInput = useSearchState((s) => s.setQ)
  const submitted = useSearchState((s) => s.submitted)
  const setSubmitted = useSearchState((s) => s.setSubmitted)
  const view = useSearchState((s) => s.view)
  const setView = useSearchState((s) => s.setView)
  const categoryKey = useSearchState((s) => s.categoryKey)
  const setCategoryKey = useSearchState((s) => s.setCategoryKey)
  const [history, setHistory] = useState<string[]>(() => readSearchHistory())
  // F079：暂停记录开关（持久化）+ 读取条目化历史（{q, filters}）。
  const [historyPaused, setHistoryPaused] = useState(() => isHistoryPaused())
  const debounced = useDebouncedValue(input)
  // pool #09：保存的搜索视图（服务端持久化；存意图，应用时重新查询）。
  const savedViews = useSavedSearchViews()
  const createView = useCreateSavedSearchViewMutation()
  const deleteView = useDeleteSavedSearchViewMutation()
  const renameView = useRenameSavedSearchViewMutation()
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  // F061：视图私有 Atom 订阅管理对话框（per-view）。
  const [feedTokenView, setFeedTokenView] = useState<SavedSearchView | null>(null)
  // F073：引用清单导出对话框。
  const [exportOpen, setExportOpen] = useState(false)
  // F075：视图对照对话框（base=点击「比较」的视图）。
  const [compareBase, setCompareBase] = useState<SavedSearchView | null>(null)

  const feeds = useFeeds()
  // F017：订阅列表（构建器「来源」选项来自真实订阅；非数组响应容错）
  const subscriptionsRaw = useSubscriptions()
  const subscriptions = {
    data: Array.isArray(subscriptionsRaw.data) ? subscriptionsRaw.data : [],
  }
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
  const hasQuery = trimmed.length > 0

  // ---- F27 日期范围 / F29 高级条件（会话内本地状态：面板开关 + 草稿 +
  //      已应用条件；search-state store 属禁改文件，且这两类条件不参与
  //      浏览器返回恢复的既有契约，会话内丢失可接受） ----
  const [datePanelOpen, setDatePanelOpen] = useState(false)
  const [advancedPanelOpen, setAdvancedPanelOpen] = useState(false)
  const [dateRange, setDateRange] = useState<{ from: string | null; to: string | null; label: string } | null>(null)
  const [advanced, setAdvanced] = useState<AdvancedTextFilter | null>(null)
  const [draftFrom, setDraftFrom] = useState('')
  const [draftTo, setDraftTo] = useState('')
  const [draftAdvanced, setDraftAdvanced] = useState<AdvancedTextFilter>({ ...EMPTY_ADVANCED_FILTER })
  // F017：条件构建器维度（来源 / 未读 / 收藏 / 仅摘要有无）
  const [builder, setBuilder] = useState<BuilderFilters>({ ...EMPTY_BUILDER_FILTERS })
  const [draftBuilder, setDraftBuilder] = useState<BuilderFilters>({ ...EMPTY_BUILDER_FILTERS })
  const advancedMode = isAdvancedSearchActive(dateRange, advanced)
  const builderActive = hasBuilderFilters(builder)

  // F27/F29：清除条件后让基础搜索重新拉取——「清除恢复全部结果」是真实
  // 请求而非沿用旧缓存（条件存在期间基础查询未卸载，单靠 remount 不会
  // 重取）。predicate 排除 'advanced' 子空间：高级缓存随条件清除自然
  // 失效，不参与重取（避免清除瞬间旧高级查询仍处于 enabled 视图状态时
  // 被一并重发）。
  const queryClient = useQueryClient()
  const refreshSearchAfterClear = () => {
    void queryClient.invalidateQueries({
      queryKey: SEARCH_RESULTS_KEY,
      predicate: (query) => query.queryKey[2] !== 'advanced',
    })
  }

  const applyQuickRange = (kind: QuickDateRangeKind) => {
    const range = quickRange(kind)
    const label = QUICK_RANGE_LABELS[kind]
    setDateRange({ ...range, label })
    setDraftFrom(range.from ?? '')
    setDraftTo(range.to ?? '')
    setDatePanelOpen(false)
  }
  const applyCustomRange = () => {
    const from = draftFrom.trim() === '' ? null : draftFrom.trim()
    const to = draftTo.trim() === '' ? null : draftTo.trim()
    if (from === null && to === null) return
    setDateRange({
      from,
      to,
      label:
        from !== null && to !== null
          ? `${from} ~ ${to}`
          : `${from !== null ? `自 ${from}` : '…'} ~ ${to !== null ? `至 ${to}` : '…'}`,
    })
    setDatePanelOpen(false)
  }
  const clearDateRange = () => {
    setDateRange(null)
    setDraftFrom('')
    setDraftTo('')
    refreshSearchAfterClear()
  }
  const applyAdvanced = () => {
    const next: AdvancedTextFilter = {
      intitle: draftAdvanced.intitle.trim(),
      phrase: draftAdvanced.phrase.trim(),
      exclude: draftAdvanced.exclude.trim(),
    }
    setBuilder({ ...draftBuilder })
    if (!hasAdvancedText(next) && !hasBuilderFilters(draftBuilder)) return
    setAdvanced(next)
    setAdvancedPanelOpen(false)
  }
  // F017：生成的查询语义（面板内实时预览）
  const builderSemantic = describeAdvancedQuery({
    q: trimmed || '…',
    sourceLabel:
      (subscriptions.data ?? []).find((sub) => sub.feedUrl === draftBuilder.sourceFeedUrl)?.title ??
      (draftBuilder.sourceFeedUrl !== null ? draftBuilder.sourceFeedUrl : null),
    unread: draftBuilder.unread,
    favorite: draftBuilder.favorite,
    hasSummary: draftBuilder.hasSummary,
    intitle: draftAdvanced.intitle.trim() || null,
    phrase: draftAdvanced.phrase.trim() || null,
    exclude: draftAdvanced.exclude.trim() || null,
  })
  const clearAdvancedField = (field: keyof AdvancedTextFilter) => {
    const becomesInactive =
      advanced !== null && !hasAdvancedText({ ...advanced, [field]: '' })
    setAdvanced((prev) => {
      if (prev === null) return prev
      const next = { ...prev, [field]: '' }
      return hasAdvancedText(next) ? next : null
    })
    if (becomesInactive) refreshSearchAfterClear()
  }

  // F28：高亮 terms（搜索词分词）与开关（设置只读消费）
  const searchHighlightMatches = useAppSettings((s) => s.settings.searchHighlightMatches)
  const searchTerms = useMemo(() => splitTerms(trimmed), [trimmed])

  // F078：同义词扩展开关（客户端默认开；关闭立即恢复原结果）。
  const [expandSynonyms, setExpandSynonyms] = useState(readExpandSynonyms())
  const search = useSearch(trimmed, {
    categoryId: categoryKey || null,
    state: view === 'unread' ? 'unread' : null,
    favorite: view === 'starred' ? true : null,
    expandSynonyms,
  })

  // ---- F27/F29 专用查询：日期/高级条件经 searchEntriesAdvanced 传递
  //      （client.ts 未暴露 intitle/phrase/exclude 且属禁改文件）。只推进
  //      RSS 腿（cursor），库腿不消费——结果区诚实标注。缓存挂在
  //      ['search','results','advanced', …] 子空间下（遵守搜索缓存分层
  //      纪律；searchFiltersOf 对该 key 布局返回 null → 状态写入只做
  //      通用翻转补丁，不做 unread/starred 移除语义，可接受）。
  const advancedSearch = useInfiniteQuery({
    queryKey: [
      ...SEARCH_RESULTS_KEY,
      'advanced',
      {
        q: trimmed,
        view,
        categoryKey,
        from: dateRange?.from ?? null,
        to: dateRange?.to ?? null,
        intitle: advanced?.intitle ?? '',
        phrase: advanced?.phrase ?? '',
        exclude: advanced?.exclude ?? '',
        sourceFeedUrl: builder.sourceFeedUrl,
        unread: builder.unread,
        favoriteB: builder.favorite,
        hasSummary: builder.hasSummary,
      },
    ],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      searchEntriesAdvanced(
        {
          q: trimmed,
          cursor: pageParam,
          categoryId: categoryKey || null,
          from: dateRange?.from ?? null,
          to: dateRange?.to ?? null,
          intitle: advanced?.intitle ?? null,
          phrase: advanced?.phrase ?? null,
          exclude: advanced?.exclude ?? null,
          feedUrl: builder.sourceFeedUrl,
          // F017 构建器维度覆盖视图级 state/favorite（仅在勾选时生效）
          state: builder.unread === true ? 'unread' : view === 'unread' ? 'unread' : null,
          favorite:
            builder.favorite === true || view === 'starred'
              ? true
              : null,
          hasSummary: builder.hasSummary,
        },
        signal,
      ),
    getNextPageParam: (lastPage) =>
      lastPage.hasMore && lastPage.nextCursor != null ? lastPage.nextCursor : undefined,
    enabled: hasQuery && (advancedMode || builderActive),
    placeholderData: keepPreviousData,
    maxPages: 50,
  })

  // 两种模式的查询结果统一取用（高级/日期模式走专用查询，否则走 useSearch）
  const activeQuery = advancedMode || builderActive ? advancedSearch : search
  const { data, isPending, isError, error, refetch, hasNextPage, isFetchingNextPage, fetchNextPage } =
    activeQuery

  // 多页合并按 ref 去重（merge-unique）：双腿独立 keyset 下同一 ref
  // 理论上只出现一次，但旧服务端会每页重发同一库腿切片。
  const results = useMemo(
    () => mergeUnique(data?.pages.flatMap((page) => page.items) ?? [], (i) => i.entryRef),
    [data],
  )
  const indexInfo = data?.pages.at(-1)?.index
  // phase2 G6：库腿（additive 字段）——多页合并；libraryError 取第一个
  // 非 null 页错误（诚实小字展示，不阻塞 RSS 结果）。
  const libraryHits = useMemo(
    () => mergeUnique(data?.pages.flatMap((page) => page.library ?? []) ?? [], (h) => h.ref),
    [data],
  )
  const libraryError = useMemo(
    () => data?.pages.map((page) => page.libraryError ?? null).find((m) => m !== null) ?? null,
    [data],
  )

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
    // F079：暂停中不落盘（pushSearchHistoryEntry 内部诚实处理）。
    if (!historyPaused) {
      setHistory((prev) => pushSearchHistory(prev, q))
    }
  }

  const cancel = () => {
    setInput('')
    setSubmitted('')
  }

  const saveCurrentView = () => {
    if (!hasQuery) return
    createView.mutate(
      { name: trimmed.slice(0, 60), query: trimmed, view, categoryKey },
      {
        onSuccess: () => {
          setInput(trimmed)
          setSubmitted(trimmed)
        },
      },
    )
  }

  const applySavedView = (saved: { query: string; view: string; categoryKey: string }) => {
    const restored = saved.query
    setCategoryKey(saved.categoryKey)
    setView(saved.view as ViewFilter)
    setInput(restored)
    setSubmitted(restored)
    setHistory((prev) => pushSearchHistory(prev, restored))
  }

  // F120：命令面板「保存的视图」数据源的动作通道——palette 侧 dispatch
  // `lumirss-open-saved-view`，这里应用（ref 持最新闭包，避免陈旧 state）。
  const applySavedViewRef = useRef(applySavedView)
  applySavedViewRef.current = applySavedView
  useEffect(() => {
    const onOpen = (event: Event) => {
      const detail = (event as CustomEvent<{ query: string; view: string; categoryKey: string }>).detail
      if (detail) applySavedViewRef.current(detail)
    }
    window.addEventListener('lumirss-open-saved-view', onOpen)
    return () => window.removeEventListener('lumirss-open-saved-view', onOpen)
  }, [])

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
              data-shortcut-target="search-input"
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

          {/* F27 日期 / F29 高级：行内面板开关（aria-expanded；互斥展开） */}
          <button
            type="button"
            data-testid="date-panel-toggle"
            aria-expanded={datePanelOpen}
            aria-pressed={dateRange !== null}
            onClick={() => {
              setDatePanelOpen((v) => !v)
              setAdvancedPanelOpen(false)
            }}
            className={cx(
              'flex min-h-7 items-center gap-1 rounded-[var(--lumi-radius-full)] px-2.5 py-1 text-xs',
              'transition-colors duration-[var(--lumi-motion-fast)]',
              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
              dateRange !== null
                ? 'bg-[var(--lumi-accent-soft)] font-medium text-[var(--lumi-accent-text)]'
                : 'border border-[var(--lumi-border)] text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]',
            )}
          >
            <Calendar aria-hidden className="size-3.5" />
            日期
          </button>
          <button
            type="button"
            data-testid="advanced-panel-toggle"
            aria-expanded={advancedPanelOpen}
            aria-pressed={advanced !== null}
            onClick={() => {
              setAdvancedPanelOpen((v) => !v)
              setDatePanelOpen(false)
            }}
            className={cx(
              'flex min-h-7 items-center gap-1 rounded-[var(--lumi-radius-full)] px-2.5 py-1 text-xs',
              'transition-colors duration-[var(--lumi-motion-fast)]',
              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
              advanced !== null
                ? 'bg-[var(--lumi-accent-soft)] font-medium text-[var(--lumi-accent-text)]'
                : 'border border-[var(--lumi-border)] text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]',
            )}
          >
            <SlidersHorizontal aria-hidden className="size-3.5" />
            高级
          </button>
        </div>

        {/* F27：日期范围行内面板（非 modal；快捷范围即时应用，自定义走应用） */}
        {datePanelOpen && (
          <div
            data-testid="date-panel"
            className="mt-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
          >
            <div role="group" aria-label="快捷日期范围" className="flex flex-wrap gap-1.5">
              {(Object.keys(QUICK_RANGE_LABELS) as QuickDateRangeKind[]).map((kind) => (
                <button
                  key={kind}
                  type="button"
                  data-testid={`quick-range-${kind}`}
                  aria-pressed={dateRange?.label === QUICK_RANGE_LABELS[kind]}
                  onClick={() => applyQuickRange(kind)}
                  className={cx(
                    'min-h-7 rounded-[var(--lumi-radius-full)] px-2.5 py-1 text-xs transition-colors duration-[var(--lumi-motion-fast)]',
                    'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                    dateRange?.label === QUICK_RANGE_LABELS[kind]
                      ? 'bg-[var(--lumi-accent-soft)] font-medium text-[var(--lumi-accent-text)]'
                      : 'border border-[var(--lumi-border)] text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]',
                  )}
                >
                  {QUICK_RANGE_LABELS[kind]}
                </button>
              ))}
            </div>
            <div className="mt-2.5 flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]">
                起
                <input
                  type="date"
                  value={draftFrom}
                  onChange={(e) => setDraftFrom(e.target.value)}
                  aria-label="开始日期"
                  className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                />
              </label>
              <label className="flex items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]">
                止
                <input
                  type="date"
                  value={draftTo}
                  onChange={(e) => setDraftTo(e.target.value)}
                  aria-label="结束日期"
                  className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                />
              </label>
              <Button size="sm" onClick={applyCustomRange}>
                应用
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setDatePanelOpen(false)
                  setDraftFrom(dateRange?.from ?? '')
                  setDraftTo(dateRange?.to ?? '')
                }}
              >
                收起
              </Button>
            </div>
            <p className="mt-2 text-xs text-[var(--lumi-text-tertiary)]">
              按本地时区日期过滤（起含当天 00:00、止含当天末尾，inclusive/exclusive 由服务端解释）；只填其一 = 单边范围。
            </p>
          </div>
        )}

        {/* F29：高级条件行内面板（非 modal；服务端 q 必填，空查询时在
            结果区诚实提示，这里不禁用面板） */}
        {advancedPanelOpen && (
          <div
            data-testid="advanced-panel"
            className="mt-2 flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
          >
            {/* F017：条件构建器（来源 / 未读 / 收藏 / 仅摘要有无） */}
            <label className="flex items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
              <span className="w-14 shrink-0">来源</span>
              <select
                value={draftBuilder.sourceFeedUrl ?? ''}
                onChange={(e) =>
                  setDraftBuilder((prev) => ({
                    ...prev,
                    sourceFeedUrl: e.target.value === '' ? null : e.target.value,
                  }))
                }
                aria-label="来源筛选"
                className="min-h-7 w-full min-w-0 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs text-[var(--lumi-text-primary)]"
              >
                <option value="">全部来源</option>
                {(subscriptions.data ?? []).map((sub) => (
                  <option key={sub.subscriptionRef} value={sub.feedUrl}>{sub.title}</option>
                ))}
              </select>
            </label>
            <div className="flex flex-wrap gap-3 text-xs text-[var(--lumi-text-secondary)]" role="group" aria-label="状态维度">
              <label className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={draftBuilder.unread === true}
                  onChange={(e) => setDraftBuilder((prev) => ({ ...prev, unread: e.target.checked ? true : null }))}
                  className="size-3.5 accent-[var(--lumi-accent)]"
                />
                仅未读
              </label>
              <label className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={draftBuilder.favorite === true}
                  onChange={(e) => setDraftBuilder((prev) => ({ ...prev, favorite: e.target.checked ? true : null }))}
                  className="size-3.5 accent-[var(--lumi-accent)]"
                />
                仅收藏
              </label>
              <label className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={draftBuilder.hasSummary === true}
                  onChange={(e) => setDraftBuilder((prev) => ({ ...prev, hasSummary: e.target.checked ? true : null }))}
                  className="size-3.5 accent-[var(--lumi-accent)]"
                />
                仅摘要有内容
              </label>
            </div>
            <label className="flex items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
              <span className="w-14 shrink-0">仅标题</span>
              <input
                type="text"
                value={draftAdvanced.intitle}
                onChange={(e) => setDraftAdvanced((prev) => ({ ...prev, intitle: e.target.value }))}
                placeholder="标题包含…"
                aria-label="仅标题"
                className="min-h-7 w-full min-w-0 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
              />
            </label>
            <label className="flex items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
              <span className="w-14 shrink-0">精确短语</span>
              <input
                type="text"
                value={draftAdvanced.phrase}
                onChange={(e) => setDraftAdvanced((prev) => ({ ...prev, phrase: e.target.value }))}
                placeholder="完整短语"
                aria-label="精确短语"
                className="min-h-7 w-full min-w-0 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
              />
            </label>
            <label className="flex items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
              <span className="w-14 shrink-0">排除词</span>
              <input
                type="text"
                value={draftAdvanced.exclude}
                onChange={(e) => setDraftAdvanced((prev) => ({ ...prev, exclude: e.target.value }))}
                placeholder="逗号或空格分隔"
                aria-label="排除词"
                className="min-h-7 w-full min-w-0 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
              />
            </label>
            <p
              data-testid="query-semantic"
              className="rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-selected)] px-2 py-1 text-[11px] leading-relaxed text-[var(--lumi-text-secondary)]"
            >
              查询语义：{builderSemantic}
            </p>
            <div className="flex gap-2">
              <Button size="sm" onClick={applyAdvanced}>
                应用
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setAdvancedPanelOpen(false)
                  setDraftAdvanced(advanced ?? { ...EMPTY_ADVANCED_FILTER })
                }}
              >
                收起
              </Button>
            </div>
          </div>
        )}

        {/* F27/F29：已应用条件 chips（可逐个清除） */}
        {(dateRange !== null || advanced !== null) && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5" aria-label="已应用筛选">
            {dateRange !== null && (
              <span className="flex items-center gap-1 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-accent-soft)] pl-2.5 pr-1 text-xs font-medium text-[var(--lumi-accent-text)]">
                <span data-testid="applied-date-label">{dateRange.label}</span>
                <button
                  type="button"
                  onClick={clearDateRange}
                  aria-label={`清除日期范围「${dateRange.label}」`}
                  className="relative flex size-6 items-center justify-center rounded-full transition-colors after:absolute after:-inset-y-2.5 after:-inset-x-1 after:content-[''] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                >
                  <X aria-hidden className="size-3" />
                </button>
              </span>
            )}
            {advanced !== null && advanced.intitle !== '' && (
              <span className="flex items-center gap-1 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-accent-soft)] pl-2.5 pr-1 text-xs font-medium text-[var(--lumi-accent-text)]">
                <span>标题: {advanced.intitle}</span>
                <button
                  type="button"
                  onClick={() => clearAdvancedField('intitle')}
                  aria-label={`清除标题条件「${advanced.intitle}」`}
                  className="relative flex size-6 items-center justify-center rounded-full transition-colors after:absolute after:-inset-y-2.5 after:-inset-x-1 after:content-[''] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                >
                  <X aria-hidden className="size-3" />
                </button>
              </span>
            )}
            {advanced !== null && advanced.phrase !== '' && (
              <span className="flex items-center gap-1 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-accent-soft)] pl-2.5 pr-1 text-xs font-medium text-[var(--lumi-accent-text)]">
                <span>短语: “{advanced.phrase}”</span>
                <button
                  type="button"
                  onClick={() => clearAdvancedField('phrase')}
                  aria-label={`清除精确短语「${advanced.phrase}」`}
                  className="relative flex size-6 items-center justify-center rounded-full transition-colors after:absolute after:-inset-y-2.5 after:-inset-x-1 after:content-[''] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                >
                  <X aria-hidden className="size-3" />
                </button>
              </span>
            )}
            {advanced !== null && advanced.exclude !== '' && (
              <span className="flex items-center gap-1 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-accent-soft)] pl-2.5 pr-1 text-xs font-medium text-[var(--lumi-accent-text)]">
                <span>排除: {advanced.exclude}</span>
                <button
                  type="button"
                  onClick={() => clearAdvancedField('exclude')}
                  aria-label={`清除排除词「${advanced.exclude}」`}
                  className="relative flex size-6 items-center justify-center rounded-full transition-colors after:absolute after:-inset-y-2.5 after:-inset-x-1 after:content-[''] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                >
                  <X aria-hidden className="size-3" />
                </button>
              </span>
            )}
          </div>
        )}

        {/* pool #09：保存当前搜索（意图而非结果集）+ 已存视图 chips */}
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <SynonymsControls expanded={expandSynonyms} onToggle={setExpandSynonyms} />
          <button
            type="button"
            data-testid="search-export-open"
            onClick={() => setExportOpen(true)}
            disabled={!hasQuery}
            className={cx(
              'min-h-7 rounded-[var(--lumi-radius-full)] border border-dashed border-[var(--lumi-border)] px-2.5 py-1 text-xs',
              'transition-colors duration-[var(--lumi-motion-fast)]',
              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
              hasQuery
                ? 'text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]'
                : 'cursor-not-allowed text-[var(--lumi-text-tertiary)] opacity-60',
            )}
          >
            导出清单
          </button>
          <button
            type="button"
            onClick={saveCurrentView}
            disabled={!hasQuery || createView.isPending}
            className={cx(
              'min-h-7 rounded-[var(--lumi-radius-full)] border border-dashed border-[var(--lumi-border)] px-2.5 py-1 text-xs',
              'transition-colors duration-[var(--lumi-motion-fast)]',
              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
              hasQuery
                ? 'text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]'
                : 'cursor-not-allowed text-[var(--lumi-text-tertiary)] opacity-60',
            )}
          >
            {createView.isPending ? '保存中…' : '+ 保存此搜索'}
          </button>
          {(savedViews.data?.items ?? []).map((saved) => (
            <div
              key={saved.id}
              className="flex items-center gap-1 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-accent-soft)] pl-2.5 pr-1"
            >
              {renamingId === saved.id ? (
                <input
                  value={renameDraft}
                  autoFocus
                  onChange={(e) => setRenameDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && renameDraft.trim() !== '') {
                      renameView.mutate({ id: saved.id, name: renameDraft.trim() })
                      setRenamingId(null)
                    }
                    if (e.key === 'Escape') setRenamingId(null)
                  }}
                  onBlur={() => setRenamingId(null)}
                  aria-label="重命名视图"
                  className="w-28 bg-transparent py-1 text-xs text-[var(--lumi-text-primary)] focus:outline-none"
                />
              ) : (
                <button
                  type="button"
                  title="点击应用；双击重命名"
                  onDoubleClick={() => {
                    setRenamingId(saved.id)
                    setRenameDraft(saved.name)
                  }}
                  onClick={() => applySavedView(saved)}
                  className="max-w-48 truncate py-1 text-xs font-medium text-[var(--lumi-accent-text)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                >
                  {saved.name}
                </button>
              )}
              <button
                type="button"
                onClick={() => setCompareBase(saved)}
                aria-label={`视图「${saved.name}」比较`}
                title="比较"
                className="relative flex size-6 items-center justify-center rounded-full text-[var(--lumi-accent-text)] transition-colors after:absolute after:-inset-y-2.5 after:-inset-x-1 after:content-[''] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
              >
                <GitCompare aria-hidden className="size-3" />
              </button>
              <button
                type="button"
                onClick={() => setFeedTokenView(saved)}
                aria-label={`视图「${saved.name}」私有订阅`}
                title="私有订阅"
                className="relative flex size-6 items-center justify-center rounded-full text-[var(--lumi-accent-text)] transition-colors after:absolute after:-inset-y-2.5 after:-inset-x-1 after:content-[''] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
              >
                <Rss aria-hidden className="size-3" />
              </button>
              <button
                type="button"
                onClick={() => deleteView.mutate(saved.id)}
                aria-label={`删除视图「${saved.name}」`}
                className="relative flex size-6 items-center justify-center rounded-full text-[var(--lumi-accent-text)] transition-colors after:absolute after:-inset-y-2.5 after:-inset-x-1 after:content-[''] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
              >
                <X aria-hidden className="size-3" />
              </button>
            </div>
          ))}
          {savedViews.isError && (
            <span role="alert" className="text-xs text-[var(--lumi-danger)]">
              已存视图加载失败
            </span>
          )}
        </div>

        {/* F023：作者聚合面板（计数/合并/取消合并；显式别名） */}
        <Suspense fallback={null}><AuthorAggregatesPanelLazy /></Suspense>

        {/* 搜索历史（本地 UI 数据；上限 10；无查询时展示） */}
        {!hasQuery && history.length > 0 && (
          <section className="mt-5" aria-label="搜索历史">
            <div className="mb-2 flex items-center justify-between px-1">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-[var(--lumi-text-tertiary)]">
                搜索历史
              </h2>
              {/* F079：暂停记录开关 */}
              <label className="flex items-center gap-1.5 text-[11px] text-[var(--lumi-text-tertiary)]">
                <input
                  type="checkbox"
                  role="switch"
                  aria-label="暂停记录搜索历史"
                  checked={historyPaused}
                  onChange={(e) => setHistoryPaused(e.target.checked)}
                />
                暂停记录
              </label>
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

        {/* 结果 / 诚实状态（库分组在 RSS 结果之后追加，不影响既有行为） */}
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
              {(indexInfo?.entryCount ?? 0) === 0 && libraryHits.length === 0 ? (
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
              <LibraryGroup items={libraryHits} error={libraryError} />
            </div>
          ) : (
            <>
              <ul className="mt-3 flex flex-col gap-1" aria-label="搜索结果">
                {results.map((item) => (
                  <ResultRow
                    key={item.entryRef}
                    item={item}
                    terms={searchTerms}
                    highlightEnabled={searchHighlightMatches}
                    lastSyncedAt={indexInfo?.lastSyncedAt ?? null}
                    libraryError={libraryError}
                  />
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
              {advancedMode && (
                <p role="note" className="px-1 pt-2 text-xs text-[var(--lumi-text-tertiary)]">
                  高级筛选仅覆盖 RSS 结果
                </p>
              )}
              {!advancedMode && <LibraryGroup items={libraryHits} error={libraryError} />}
            </>
          )
        ) : advancedMode ? (
          // F29 诚实约束：服务端 q 必填——空查询 + 仅高级/日期条件时
          // 明确提示，不发请求、不禁用面板。
          <div className="mt-6" role="status" data-testid="advanced-needs-query">
            <EmptyState
              icon={<SlidersHorizontal aria-hidden className="size-8" />}
              title="请输入至少一个搜索词"
              description="日期与高级条件需要配合搜索关键词使用（服务端要求 q 非空）。"
            />
          </div>
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
      {/* F061：视图私有 Atom 订阅（启用/复制仅展示一次/轮换） */}
      {/* F073：引用清单导出 */}
      <SearchExportDialog
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        query={debounced}
      />
      {/* F075：视图对照（选第二视图→三区面板） */}
      <ViewCompareDialog
        open={compareBase !== null}
        onClose={() => setCompareBase(null)}
        baseView={compareBase}
        otherViews={savedViews.data?.items ?? []}
      />
      <ViewFeedTokenDialog
        open={feedTokenView !== null}
        onClose={() => setFeedTokenView(null)}
        view={
          feedTokenView !== null
            ? {
                id: feedTokenView.id,
                name: feedTokenView.name,
                hasFeedToken: feedTokenView.hasFeedToken,
              }
            : null
        }
      />
    </div>
  )
}
