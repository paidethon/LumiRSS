import { Inbox, Clock, Loader2, PanelLeft, PanelLeftClose, Unplug, CheckSquare, ChevronDown, X, RotateCw } from 'lucide-react'
import { Fragment, lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'

// Bundle guard：对话框/工具面板非列表首屏必需——懒加载分包。
const AskBatchDialog = lazy(() => import('./AskBatchDialog').then((m) => ({ default: m.AskBatchDialog })))
const ReadingBudgetPanel = lazy(() => import('./ReadingBudgetPanel').then((m) => ({ default: m.ReadingBudgetPanel })))
const ReadingQueuePanel = lazy(() => import('./ReadingQueuePanel').then((m) => ({ default: m.ReadingQueuePanel })))
const BacklogPanel = lazy(() => import('./BacklogPanel').then((m) => ({ default: m.BacklogPanel })))
// E1: N037 断更恢复横幅 + N047 收录撞车提示 toast
const RecoveryBanner = lazy(() => import('./RecoveryBanner').then((m) => ({ default: m.RecoveryBanner })))
const DuplicateWarningToast = lazy(() => import('./DuplicateWarningToast').then((m) => ({ default: m.DuplicateWarningToast })))
// E1: N050 阅读路径面板（设备本地；tools 行入口）
const ReadingPathPanel = lazy(() => import('./ReadingPathPanel').then((m) => ({ default: m.ReadingPathPanel })))
const CompareRead = lazy(() => import('./CompareRead'))
import {
  useEntries,
  useEntryStateMutation,
  useFeeds,
  useReadLaterLastError,
  useReadLaterMemberMutation,
  useReadLaterTimeline,
} from '../api/queries'
import type { UiView } from '../lib/read-later'
import type { EntryListItem, ReadLaterItem } from '../api/types'
import { useReaderUi } from '../store/reader-ui'
import { recordReadingPathEntry } from '../lib/reading-path'
import { scopeKey, scopeTitle } from '../lib/navigation'
import { useAppSettings } from '../store/app-settings'
import { groupEntriesByDate } from '../lib/entry-groups'
import { listAnchorKey, loadListAnchor, saveListAnchor } from '../lib/list-anchor'
import { matchesFilterRules } from '../lib/feed-filter-match'
import EntryCard from './EntryCard'
import EntryRow from './EntryRow'
import { Button } from './ui/Button'
import { EmptyState } from './ui/EmptyState'
import { IconButton } from './ui/IconButton'
import { UnifiedContentCard } from './UnifiedContentCard'
import { Skeleton } from './ui/Skeleton'
import { cx } from './ui/cx'
import { aggregateByNormalizedUrl, type UrlGroup } from '../lib/url-aggregate'
import type { BudgetCandidate } from '../lib/reading-budget'

const EMPTY_TEXTS: Record<UiView, { title: string; description: string }> = {
  all: { title: '这里还没有文章', description: '订阅源还没有内容，稍后再来看看。' },
  unread: { title: '没有未读文章', description: '全部读完了，干得漂亮。' },
  starred: { title: '还没有收藏文章', description: '阅读时点击「收藏」，文章会出现在这里。' },
  // §29：稍后读专属空态（不做大型插画，保持 EmptyState 风格）
  'read-later': {
    title: '还没有稍后读的文章',
    description: '在文章列表或阅读页面点击时钟图标，就可以把文章留到之后阅读。',
  },
}

/** 列表分发：read-later 是服务端时间线视图（P0-01），与 entries 查询
 * 完全分道——两个子组件各自持 hooks（避免同组件内条件 hooks）。 */
export default function EntryList() {
  const view = useReaderUi((s) => s.view)
  return view === 'read-later' ? <ReadLaterList /> : <EntriesList />
}

/** 无限滚动哨兵 hook：滚入视口自动 fetchNextPage（EntriesList 与
 * ReadLaterList 共用同一模式；jsdom 测试 stub 掉 IntersectionObserver）。 */
function useInfiniteSentinel(
  hasNextPage: boolean,
  isFetchingNextPage: boolean,
  fetchNextPage: () => void,
  depsKey: number,
) {
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
      // 提前半屏预拉取，减少等待感
      { rootMargin: '0px 0px 50% 0px' },
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [hasNextPage, isFetchingNextPage, fetchNextPage, depsKey])
  return sentinelRef
}

/** P1.3 列表滚动锚点：离开/滚动时保存，挂载/换范围后数据到达时恢复
 * （rAF 节流保存；恢复对 scrollHeight 有要求，等一拍重试）。 */
function useListScrollAnchor(
  containerRef: React.RefObject<HTMLDivElement | null>,
  anchorKey: string,
  loadedCount: number,
) {
  useEffect(() => {
    const container = containerRef.current
    if (container === null) return
    const restore = (attempt: number) => {
      const target = loadListAnchor(anchorKey)
      if (target === null || target === 0) return
      if (container.scrollHeight > target || attempt > 20) {
        container.scrollTop = target
      } else {
        // 内容还没长到锚点位置（下一页仍在拉）：稍后重试。
        requestAnimationFrame(() => restore(attempt + 1))
      }
    }
    restore(0)
  }, [anchorKey, loadedCount, containerRef])

  useEffect(() => {
    const container = containerRef.current
    if (container === null) return
    let scheduled = false
    const onSave = () => {
      if (scheduled) return
      scheduled = true
      requestAnimationFrame(() => {
        scheduled = false
        const el = containerRef.current
        if (el !== null) saveListAnchor(anchorKey, el.scrollTop)
      })
    }
    container.addEventListener('scroll', onSave, { passive: true })
    return () => {
      container.removeEventListener('scroll', onSave)
      const el = containerRef.current
      if (el !== null) saveListAnchor(anchorKey, el.scrollTop)
    }
  }, [anchorKey, containerRef])
}

/** 列表尾部状态（加载中 / 可加载更多 / 到底；ref 由调用方传入——
 * IntersectionObserver 的观察目标就是本 li）。 */
function SentinelState({
  sentinelRef,
  hasNextPage,
  isFetchingNextPage,
}: {
  sentinelRef: React.RefObject<HTMLLIElement | null>
  hasNextPage: boolean
  isFetchingNextPage: boolean
}) {
  return (
    <li
      ref={sentinelRef}
      aria-hidden={hasNextPage || isFetchingNextPage ? undefined : 'true'}
      className="flex items-center justify-center py-4 max-lg:pb-[84px]"
      style={{ paddingBottom: hasNextPage || isFetchingNextPage ? undefined : 'max(1rem, var(--safe-bottom))' }}
    >
      {isFetchingNextPage ? (
        <Loader2
          aria-label="加载中"
          className="size-4 animate-spin text-[var(--lumi-text-tertiary)]"
        />
      ) : hasNextPage ? (
        <span className="text-xs text-[var(--lumi-text-tertiary)]">下滑加载更多…</span>
      ) : (
        <span className="text-xs text-[var(--lumi-text-tertiary)]">已经到底了</span>
      )}
    </li>
  )
}

/** 桌面列表头（scope 标题 + 视图后缀 + 折叠开关）。 */
function ListHeader({ view, loadedCount }: { view: UiView; loadedCount: number }) {
  const scope = useReaderUi((s) => s.scope)
  const updateSettings = useAppSettings((s) => s.update)
  const timelineCollapsed = useAppSettings((s) => s.settings.timelineCollapsed)
  const feeds = useFeeds()
  return (
    <header className="hidden items-center gap-2 border-b border-[var(--lumi-separator)] px-4 py-2.5 lg:flex">
      <div className="min-w-0 flex-1">
        <h2 className="text-sm font-semibold text-[var(--lumi-text-primary)]">
          {scope.kind === 'rss-feed'
            ? (feeds.data?.find((f) => f.feedUrl === scope.feedUrl)?.title ?? '订阅源')
            : scopeTitle(scope)}
          {view === 'unread' && <span className="ml-1.5 font-normal text-[var(--lumi-text-tertiary)]">· 未读</span>}
          {view === 'read-later' && <span className="ml-1.5 font-normal text-[var(--lumi-text-tertiary)]">· 稍后读</span>}
        </h2>
        <p className="text-xs text-[var(--lumi-text-tertiary)]">已加载 {loadedCount} 条</p>
      </div>
      <button
        type="button"
        onClick={() => updateSettings({ timelineCollapsed: !timelineCollapsed })}
        aria-label={timelineCollapsed ? '显示文章列表' : '隐藏文章列表'}
        aria-pressed={timelineCollapsed}
        title={timelineCollapsed ? '显示文章列表' : '隐藏文章列表'}
        className="hidden size-7 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)] lg:flex"
      >
        {timelineCollapsed ? (
          <PanelLeft aria-hidden className="size-4 rotate-180" />
        ) : (
          <PanelLeftClose aria-hidden className="size-4 rotate-180" />
        )}
      </button>
    </header>
  )
}

/** P0-01：稍后读视图 = 服务端时间线（排序偏好 readLaterSort：最新/最早
 * 加入；cursor 分页且与排序绑定；悬挂成员以 stale 行可见而非消失——
 * 服务端是真源，ADR 0004）。行卡片复用 EntryRow/EntryCard（Clock 按钮
 * 经 useToggleReadLater 走 workspace mutation：乐观移除 + 失败回滚）；
 * stale 行给移除出口。 */
function ReadLaterList() {
  const readLaterSort = useAppSettings((s) => s.settings.readLaterSort)
  const updateSettings = useAppSettings((s) => s.update)
  const listDensity = useAppSettings((s) => s.settings.listDensity)
  const order: 'newest' | 'oldest' = readLaterSort
  const timeline = useReadLaterTimeline(order)
  const { data, isPending, isError, error, refetch, hasNextPage, isFetchingNextPage, fetchNextPage } = timeline
  // 列表级失败告警：乐观移除会让行组件卸载（行级错误态随之丢失），
  // 失败信息由 useReadLaterMemberMutation 写入共享 cache，在此诚实展示。
  const lastError = useReadLaterLastError()

  const rows = useMemo(() => data?.pages.flatMap((page) => page.items) ?? [], [data])
  const sentinelRef = useInfiniteSentinel(hasNextPage, isFetchingNextPage, fetchNextPage, rows.length)

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ListHeader view="read-later" loadedCount={rows.length} />
      <div className="flex items-center justify-end border-b border-[var(--lumi-separator)] px-4 py-1">
        <button
          type="button"
          aria-pressed={order === 'oldest'}
          title="切换：最早加入 / 最新加入"
          onClick={() =>
            updateSettings({ readLaterSort: order === 'newest' ? 'oldest' : 'newest' })
          }
          className={
            'rounded-[var(--lumi-radius-full)] px-2.5 py-1 text-xs transition-colors duration-[var(--lumi-motion-fast)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)] ' +
            (order === 'oldest'
              ? 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]'
              : 'text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-text-secondary)]')
          }
        >
          {order === 'oldest' ? '最早加入' : '最新加入'}
        </button>
      </div>
      {lastError.data != null && (
        <p role="alert" className="border-b border-[var(--lumi-separator)] px-4 py-1.5 text-xs text-[var(--lumi-danger)]">
          稍后读操作失败：{lastError.data}（列表已恢复）
        </p>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {isPending && (
          <div className="flex flex-col gap-3 p-4" aria-label="稍后读加载中">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="flex flex-col gap-1.5">
                <Skeleton className="h-3 w-2/5" />
                <Skeleton className="h-4 w-4/5" />
              </div>
            ))}
          </div>
        )}

        {isError && (
          <div className="p-4 text-sm text-[var(--lumi-danger)]" role="alert">
            <p>稍后读加载失败</p>
            <p className="mt-1 text-xs text-[var(--lumi-text-secondary)]">{error.message}</p>
            <Button
              size="sm"
              onClick={() => refetch()}
              className="mt-2 max-lg:w-full"
            >
              重试
            </Button>
          </div>
        )}

        {!isPending && !isError && rows.length === 0 && (
          <EmptyState
            icon={<Clock />}
            title={EMPTY_TEXTS['read-later'].title}
            description={EMPTY_TEXTS['read-later'].description}
            className="h-full"
          />
        )}

        {rows.length > 0 && (
          <ul data-density={listDensity} className="max-lg:divide-none lg:divide-y lg:divide-[var(--lumi-separator)]">
            {rows.map((row) => (
              <ReadLaterRow key={row.itemRef} row={row} />
            ))}
            {!isPending && !isError && (
              <SentinelState
                sentinelRef={sentinelRef}
                hasNextPage={hasNextPage}
                isFetchingNextPage={isFetchingNextPage}
              />
            )}
          </ul>
        )}
      </div>
    </div>
  )
}

/** 时间线单行：entry 卡片（RSS 投影）/ resolved 卡片（库类成员，
 * Q-P1-05）/ stale 行（悬挂成员，诚实可见）。 */
function ReadLaterRow({ row }: { row: ReadLaterItem }) {
  const remove = useReadLaterMemberMutation()
  if (row.entry !== null && row.entry !== undefined) {
    // SearchItem 是 EntryListItem 的结构超集（entryRef/title/feedTitle/
    // read/starred 必备），行组件直接复用；Clock 的激活态来自服务端
    // refs 清单——点「从稍后读移除」经 mutation 乐观移除该行。
    const fullRef = `rss:${row.entry.entryRef}`
    return (
      <li>
        <div className="max-lg:px-2 max-lg:py-1">
          <div className="max-lg:hidden">
            <EntryRow item={row.entry} selected={false} />
          </div>
          <div className="lg:hidden">
            <EntryCard item={row.entry} selected={false} />
          </div>
        </div>
        {remove.isError && remove.variables?.itemRef === fullRef && (
          <p role="alert" className="mt-1 px-4 pb-1 text-xs text-[var(--lumi-danger)]">
            移除失败：{remove.error instanceof Error ? remove.error.message : '请稍后重试。'}
          </p>
        )}
      </li>
    )
  }
  if (row.resolved !== null && row.resolved !== undefined) {
    // 库类成员（收件推送、剪藏等）：统一注册表视图卡片，按 kind 打开；
    // 移除走同一 mutation（完整 itemRef）。
    return (
      <li className="px-4 py-3">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <UnifiedContentCard item={row.resolved} />
          </div>
          <IconButton
            icon={
              remove.isPending && remove.variables?.itemRef === row.itemRef ? (
                <Loader2 aria-hidden className="size-4 animate-spin" />
              ) : (
                <Unplug aria-hidden className="size-4" />
              )
            }
            label="从稍后读移除"
            size="sm"
            touch
            disabled={remove.isPending}
            onClick={() => remove.mutate({ itemRef: row.itemRef, add: false })}
          />
        </div>
        {remove.isError && remove.variables?.itemRef === row.itemRef && (
          <p role="alert" className="mt-1 text-xs text-[var(--lumi-danger)]">
            移除失败：{remove.error instanceof Error ? remove.error.message : '请稍后重试。'}
          </p>
        )}
      </li>
    )
  }
  // 悬挂成员：卡片缺失（条目已从源删除 / ref 无效）——保留在列表并给
  // 移除出口，绝不静默隐藏（服务端 stale 契约）。
  return (
    <li className="px-4 py-3" data-stale-row={row.itemRef}>
      <div className="flex items-start gap-2">
        <Unplug aria-hidden className="mt-0.5 size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />
        <div className="min-w-0 flex-1">
          <p className="text-sm text-[var(--lumi-text-secondary)]">条目已失效或不存在</p>
          <p className="mt-0.5 truncate text-xs text-[var(--lumi-text-tertiary)]">
            {row.itemRef} · 加入于 {new Date(row.addedAt).toLocaleString()}
          </p>
          {remove.isError && remove.variables?.itemRef === row.itemRef && (
            <p role="alert" className="mt-1 text-xs text-[var(--lumi-danger)]">
              移除失败：{remove.error instanceof Error ? remove.error.message : '请稍后重试。'}
            </p>
          )}
        </div>
        <IconButton
          icon={
            remove.isPending && remove.variables?.itemRef === row.itemRef ? (
              <Loader2 aria-hidden className="size-4 animate-spin" />
            ) : (
              <Unplug aria-hidden className="size-4" />
            )
          }
          label="从稍后读移除失效条目"
          size="sm"
          touch
          disabled={remove.isPending}
          onClick={() => remove.mutate({ itemRef: row.itemRef, add: false })}
        />
      </div>
    </li>
  )
}

// ---- F05 按来源分组（纯函数，可单测） ----

/** 来源分组：Map<feedTitle, items> 保持首次出现顺序；feedUrl 取组内
 * 第一项的 feedUrl（可能为 null——组头「只看此来源」按钮据此禁用，
 * 绝不用后续条目回填伪造目标）。 */
export interface EntryFeedGroup {
  feedTitle: string
  feedUrl: string | null
  items: EntryListItem[]
}

export function groupEntriesByFeed(entries: EntryListItem[]): EntryFeedGroup[] {
  const map = new Map<string, EntryFeedGroup>()
  for (const item of entries) {
    const title =
      item.feedTitle !== undefined && item.feedTitle !== null && item.feedTitle.trim() !== ''
        ? item.feedTitle
        : '来源未知'
    const existing = map.get(title)
    if (existing !== undefined) {
      existing.items.push(item)
    } else {
      map.set(title, { feedTitle: title, feedUrl: item.feedUrl ?? null, items: [item] })
    }
  }
  return [...map.values()]
}

// ---- F07 多选批量（类型与常量） ----

type BatchKind = 'read' | 'star' | 'readLater'

const BATCH_LABELS: Record<BatchKind, string> = {
  read: '标为已读',
  star: '收藏',
  readLater: '加入稍后读',
}

/** 批量上限：超出后动作按钮禁用并诚实提示（防止一次发出过大的请求串）。 */
const BATCH_LIMIT = 100

// ---- F09 下拉刷新（常量） ----

/** 触发刷新的下拉阈值（显示位移，非手指位移）。 */
const PULL_THRESHOLD_PX = 60
/** 跟手位移上限（指示区最大高度）。 */
const PULL_MAX_PX = 64
/** touchstart 允许进入下拉手势的顶部区域（相对滚动容器）。 */
const PULL_START_ZONE_PX = 60

/** entries 视图列表（all / unread / starred；read-later 走 ReadLaterList）。
 *
 * 2026-09 批次新增：F05 按来源分组 / F06 排序切换 / F07 多选批量 /
 * F09 下拉刷新（均为列表展示层行为，不改服务端契约）。 */
function EntriesList() {
  const view = useReaderUi((s) => s.view) as Exclude<UiView, 'read-later'>
  const scope = useReaderUi((s) => s.scope)
  const section = useReaderUi((s) => s.section)
  const selectedEntryRef = useReaderUi((s) => s.selectedEntryRef)
  // F014：阅读预算（会话内临时清单）
  const selectEntry = useReaderUi((s) => s.selectEntry)
  const [budgetOpen, setBudgetOpen] = useState(false)
  // N041：今日必读面板开关（服务端持久化队列）
  const [queueOpen, setQueueOpen] = useState(false)
  // F024：积压整理面板开关
  const [backlogOpen, setBacklogOpen] = useState(false)
  const openEntry = (entryRef: string) => selectEntry(entryRef)
  // F016：对照阅读（恰好选中 2 条时可用；关闭恢复原列表）
  const [compareRefs, setCompareRefs] = useState<[string, string] | null>(null)
  // F018：同链聚合（展示层；仅折叠当前页内同链，诚实标注「仅本页」）
  const [aggregateOn, setAggregateOn] = useState(false)
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set())
  const selectScope = useReaderUi((s) => s.selectScope)
  // 0010a Gate E（AC9）：实验性滚动标记已读（默认关）
  const scrollMarkUnread = useAppSettings((s) => s.settings.scrollMarkUnread)
  // 0010a Gate E（AC7）：按日期分组
  const groupByDate = useAppSettings((s) => s.settings.groupByDate)
  // 0010a Gate F（AC24）：显示层过滤（全局规则，BFF 层 planned·0013）
  const filterRules = useAppSettings((s) => s.settings.filterRules)
  const filterEnabled = filterRules.some((r) => r.enabled)
  // F01：列表密度（卡片/行内边距与行距；不缩小触控目标）
  const listDensity = useAppSettings((s) => s.settings.listDensity)
  // F05：按来源分组
  const listGroupByFeed = useAppSettings((s) => s.settings.listGroupByFeed)
  // F06：时间线排序（最新/最早优先）
  const timelineOrder = useAppSettings((s) => s.settings.timelineOrder)
  const updateSettings = useAppSettings((s) => s.update)

  // N034：received 交给服务端（?sort=received）；newest/oldest 仍为客户端重排。
  const entriesQuery = useEntries(scope, view, timelineOrder)
  const { data, isPending, isError, error, refetch } = entriesQuery
  const hasNextPage = entriesQuery.hasNextPage
  const isFetchingNextPage = entriesQuery.isFetchingNextPage
  const fetchNextPage = entriesQuery.fetchNextPage

  // useMemo：data 引用稳定时 entries 引用也稳定（避免 effect 依赖每渲染变化）
  // P0-01：read-later 客户端过滤已删除——本组件只服务 entries 视图。
  // F06 有意为之的诚实降级：useEntries 不支持 order 参数（服务端分页
  // 恒为最新优先）；oldest 时把已加载页在客户端 reverse，只对「当前已
  // 加载范围」生效，列表头常驻标注说明这一点（测试断言该标注）。
  const entries = useMemo(() => {
    const all = data?.pages.flatMap((page) => page.items) ?? []
    const filtered = filterEnabled
      ? all.filter((item) => matchesFilterRules(item.title, filterRules, null) === null)
      : all
    return timelineOrder === 'oldest' ? [...filtered].reverse() : filtered
  }, [data, filterEnabled, filterRules, timelineOrder])

  // E1: N050 设备本地阅读路径记录（打开条目即记；仅 localStorage，
  // 不发任何请求——服务端没有任何承载端点）。
  const [readingPathOpen, setReadingPathOpen] = useState(false)
  const selectedEntry = useMemo(
    () => entries.find((item) => item.entryRef === selectedEntryRef) ?? null,
    [entries, selectedEntryRef],
  )
  useEffect(() => {
    if (selectedEntryRef === null || selectedEntryRef === undefined) return
    recordReadingPathEntry(`rss:${selectedEntryRef}`, selectedEntry?.title ?? null)
  }, [selectedEntryRef, selectedEntry?.title])

  // N034 排序切换（最新优先 → 最早优先 → 按接收时间）。
  const cycleTimelineOrder = () => {
    updateSettings({
      timelineOrder:
        timelineOrder === 'newest'
          ? 'oldest'
          : timelineOrder === 'oldest'
            ? 'received'
            : 'newest',
    })
  }

  // F014：未读候选（当前已加载 + 当前筛选；阅读预算装填输入）
  const budgetCandidates = useMemo<BudgetCandidate[]>(
    () =>
      entries
        .filter((item) => !item.read)
        .map((item) => ({
          entryRef: item.entryRef,
          title: item.title,
          text: item.snippet ?? null,
        })),
    [entries],
  )

  // F018：同链聚合组表（entries 依赖；仅当前已加载页）
  const urlGroups = useMemo(
    () => (aggregateOn ? aggregateByNormalizedUrl<EntryListItem>(entries) : null),
    [aggregateOn, entries],
  )
  const toggleGroupExpand = (ref: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(ref)) next.delete(ref)
      else next.add(ref)
      return next
    })
  }

  // F05：按来源分组（仅在设置开启时计算）
  const feedGroups = useMemo(
    () => (listGroupByFeed ? groupEntriesByFeed(entries) : []),
    [listGroupByFeed, entries],
  )
  // F05：折叠集合（会话内本地状态；fold 语义只影响展示）
  const [collapsedFeeds, setCollapsedFeeds] = useState<Set<string>>(new Set())
  const toggleFeedCollapse = (feedTitle: string) => {
    setCollapsedFeeds((prev) => {
      const next = new Set(prev)
      if (next.has(feedTitle)) next.delete(feedTitle)
      else next.add(feedTitle)
      return next
    })
  }

  // ---- F07 多选批量 ----
  const [selectMode, setSelectMode] = useState(false)
  const [selectedRefs, setSelectedRefs] = useState<Set<string>>(new Set())
  const [batch, setBatch] = useState<{ kind: BatchKind; running: boolean; failed: string[] } | null>(null)
  // F065：多篇共同问答（多选 ≥1 打开对话框）。
  const [askOpen, setAskOpen] = useState(false)
  const { mutateAsync: mutateEntryStateAsync } = useEntryStateMutation()
  // 批量稍后读直接用底层成员 mutation（add 语义）：useToggleReadLater 的
  // toggle 是「按服务端状态翻转」且不返回 Promise——批量场景下翻转会让
  // 已在稍后读的条目被移除（违反「批量=加入」直觉），也无法逐条收集失败。
  const readLaterMember = useReadLaterMemberMutation()
  const overLimit = selectedRefs.size > BATCH_LIMIT
  const batchRunning = batch?.running === true

  const toggleSelect = useCallback((ref: string) => {
    setSelectedRefs((prev) => {
      const next = new Set(prev)
      if (next.has(ref)) next.delete(ref)
      else next.add(ref)
      return next
    })
  }, [])

  const exitSelectMode = useCallback(() => {
    setSelectMode(false)
    setSelectedRefs(new Set())
    setBatch(null)
  }, [])

  /** 批量执行：mutateAsync 串行（逐条 await，控制并发）；失败逐条记录，
   * 全部成功后清空选择并退出多选，有失败则保留失败清单供重试。 */
  const runBatch = async (kind: BatchKind, refs: string[]) => {
    if (refs.length === 0 || overLimit || batchRunning) return
    setBatch({ kind, running: true, failed: [] })
    const failed: string[] = []
    for (const ref of refs) {
      try {
        if (kind === 'read') {
          await mutateEntryStateAsync({ entryRef: ref, patch: { read: true } })
        } else if (kind === 'star') {
          await mutateEntryStateAsync({ entryRef: ref, patch: { starred: true } })
        } else {
          await readLaterMember.mutateAsync({ itemRef: `rss:${ref}`, add: true })
        }
      } catch {
        failed.push(ref)
      }
    }
    if (failed.length > 0) {
      setBatch({ kind, running: false, failed })
    } else {
      setBatch(null)
      setSelectMode(false)
      setSelectedRefs(new Set())
    }
  }

  const sentinelRef = useInfiniteSentinel(hasNextPage, isFetchingNextPage, fetchNextPage, entries.length)

  // P1.3：列表滚动锚点（打开文章 → 返回原位置）。
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  useListScrollAnchor(
    scrollContainerRef,
    listAnchorKey({ section, view, scope: String(JSON.stringify(scopeKey(scope))) }),
    entries.length,
  )

  // ---- F09 下拉刷新（刷新列表数据 refetch；绝不触发上游抓取） ----
  const [pull, setPull] = useState<{ startY: number; offset: number } | null>(null)
  const [refreshState, setRefreshState] = useState<'idle' | 'refreshing' | 'done' | 'error'>('idle')
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(
    () => () => {
      if (refreshTimerRef.current !== null) clearTimeout(refreshTimerRef.current)
    },
    [],
  )

  const onTouchStart = (event: React.TouchEvent) => {
    if (refreshState !== 'idle') return
    const container = scrollContainerRef.current
    const touch = event.touches[0]
    if (container === null || touch === undefined) return
    // 只在列表滚动到顶、且触点落在容器顶部 60px 内时进入下拉手势
    if (container.scrollTop > 0) return
    const rect = container.getBoundingClientRect()
    if (touch.clientY - rect.top > PULL_START_ZONE_PX) return
    setPull({ startY: touch.clientY, offset: 0 })
  }
  const onTouchMove = (event: React.TouchEvent) => {
    setPull((prev) => {
      if (prev === null) return prev
      const touch = event.touches[0]
      if (touch === undefined) return prev
      const dy = touch.clientY - prev.startY
      if (dy <= 0) return prev.offset === 0 ? prev : { ...prev, offset: 0 }
      // 跟手阻尼：手指位移 × 0.4，上限 64px
      return { ...prev, offset: Math.min(PULL_MAX_PX, Math.round(dy * 0.4)) }
    })
  }
  const onTouchEnd = () => {
    const current = pull
    setPull(null)
    if (current === null || current.offset < PULL_THRESHOLD_PX) return
    void triggerRefresh()
  }
  const triggerRefresh = async () => {
    if (refreshState !== 'idle') return
    setRefreshState('refreshing')
    try {
      const result = await refetch()
      // 刷新后回到顶部锚点（下拉手势只在 scrollTop===0 时可进入）
      const container = scrollContainerRef.current
      if (container !== null) container.scrollTop = 0
      // TanStack v5：refetch 不 reject，错误在 result.error
      if (result.error !== null && result.error !== undefined) {
        setRefreshState('error') // 失败保留列表，指示条常驻直到下次下拉
        return
      }
      setRefreshState('done')
      refreshTimerRef.current = setTimeout(() => setRefreshState('idle'), 1500)
    } catch {
      setRefreshState('error')
    }
  }

  // ---- 滚动标记已读（0017 正式化）：IntersectionObserver + 保守策略 ----
  const { mutate: markReadMutate } = useEntryStateMutation()
  // entryRef → <li> 元素（observer 观察目标）
  const rowRefs = useRef(new Map<string, HTMLLIElement>())
  // 最新 read 状态（observer 回调闭包里读，避免过期）
  const readState = useRef(new Map<string, boolean>())
  // 曾进入视口的条目（初始加载时视口下方的不算）；已派发标记的条目（防重复）
  const seen = useRef(new Set<string>())
  const dispatched = useRef(new Set<string>())
  // 0017：手动未读保护——列表数据中出现 read true→false 的条目视为手动
  // 未读，本轮滚动周期内不再自动标记（重新滚入视口才解除保护）。
  const manuallyUnread = useRef(new Set<string>())
  // 当前正在视口中的条目（settle 防抖时复核）
  const intersecting = useRef(new Set<string>())
  // exit → 派发的 settle 计时器（快速滚回时取消）
  const settleTimers = useRef(new Map<string, ReturnType<typeof setTimeout>>())
  // 滚动标记已读的离开确认窗口（保守：短暂停顿确认，非瞬时）
  const SETTLE_MS = 400

  useEffect(() => {
    const previous = readState.current
    const next = new Map(entries.map((e) => [e.entryRef, e.read]))
    // 手动未读检测：read true → false 的条目本轮不再自动标记
    for (const [ref, wasRead] of previous) {
      if (wasRead && next.get(ref) === false) {
        manuallyUnread.current.add(ref)
      }
    }
    readState.current = next
  }, [entries])

  useEffect(() => {
    const rows = rowRefs.current
    if (!scrollMarkUnread || rows.size === 0) return
    const observer = new IntersectionObserver(
      (records) => {
        for (const r of records) {
          const ref = (r.target as HTMLElement).dataset.entryRowRef
          if (!ref) continue
          if (r.isIntersecting) {
            // 重新进入视口：取消 pending 标记并解除手动未读保护
            const timer = settleTimers.current.get(ref)
            if (timer !== undefined) {
              clearTimeout(timer)
              settleTimers.current.delete(ref)
            }
            intersecting.current.add(ref)
            seen.current.add(ref)
            manuallyUnread.current.delete(ref)
          } else {
            intersecting.current.delete(ref)
            // 完全滚出上方才算读完（滚到下方的尚未读）
            if (
              r.boundingClientRect.bottom < 0 &&
              seen.current.has(ref) &&
              !dispatched.current.has(ref) &&
              !manuallyUnread.current.has(ref) &&
              readState.current.get(ref) === false
            ) {
              // 0017：离开视口后短暂停顿确认，期间滚回则取消（快速
              // 甩动经过的文章仍会被标记，但留出误触撤回窗口）
              const timer = settleTimers.current.get(ref)
              if (timer !== undefined) clearTimeout(timer)
              settleTimers.current.set(
                ref,
                setTimeout(() => {
                  settleTimers.current.delete(ref)
                  if (
                    !intersecting.current.has(ref) &&
                    !dispatched.current.has(ref) &&
                    !manuallyUnread.current.has(ref) &&
                    readState.current.get(ref) === false
                  ) {
                    dispatched.current.add(ref)
                    markReadMutate({ entryRef: ref, patch: { read: true } })
                  }
                }, SETTLE_MS),
              )
            }
          }
        }
      },
      // 需要知道「离开」时机：默认阈值 0 会在完全离开时回调一次
    )
    for (const el of rows.values()) observer.observe(el)
    return () => {
      observer.disconnect()
      for (const timer of settleTimers.current.values()) clearTimeout(timer)
      settleTimers.current.clear()
    }
  }, [scrollMarkUnread, entries, markReadMutate])

  // 0010a F3（AC24）：过滤统计——被过滤条目数计入 stats（仅在规则启用时）
  const totalAll = data?.pages.reduce((n, page) => n + page.items.length, 0) ?? 0
  const filteredCount = filterEnabled ? totalAll - entries.length : 0
  const statsRecorded = useRef(0)
  useEffect(() => {
    if (filteredCount <= 0 || statsRecorded.current === filteredCount) return
    const s = useAppSettings.getState().settings.filterStats
    statsRecorded.current = filteredCount
    useAppSettings.getState().update({
      filterStats: { totalFiltered: s.totalFiltered + filteredCount, lastFilteredAt: Date.now(), lastMatchedRule: s.lastMatchedRule },
    })
  }, [filteredCount])

  /** 行渲染（F05 两种分组模式共用；F07 多选 props 下发行组件）。 */
  const renderRow = (item: EntryListItem) => (
    <li
      key={item.entryRef}
      data-entry-row-ref={item.entryRef}
      // Phase H/I：视口外行跳过 layout/paint（渲染成本
      // 与视口成正比；DOM 保留，滚动恢复不受影响）。
      className="lumi-row-cv"
      ref={(el) => {
        if (el) rowRefs.current.set(item.entryRef, el)
        else rowRefs.current.delete(item.entryRef)
      }}
    >
      {/* F018：同链聚合组头（仅本页内折叠；展开列出各自来源与时间） */}
      {urlGroups !== null &&
        (() => {
          const group: UrlGroup<EntryListItem> | undefined = urlGroups.groups.get(item.entryRef)
          if (group === undefined) return null
          const expanded = expandedGroups.has(item.entryRef)
          return (
            <li className="bg-[var(--lumi-surface-selected)] px-4 py-1" data-testid="same-link-header">
              <button
                type="button"
                aria-expanded={expanded}
                onClick={() => toggleGroupExpand(item.entryRef)}
                className="flex min-h-7 w-full items-center gap-1.5 text-left text-[11px] text-[var(--lumi-text-secondary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
              >
                <ChevronDown aria-hidden className={cx('size-3 transition-transform', !expanded && '-rotate-90')} />
                <span data-testid="same-link-count">{group.duplicates.length + 1} 个来源收录</span>
                <span className="text-[var(--lumi-text-tertiary)]">（仅本页 · 归一化 {group.key}）</span>
              </button>
              {expanded && (
                <ul className="mt-0.5 flex flex-col gap-0.5 pb-1">
                  {group.duplicates.map((dup) => (
                    <li key={dup.entryRef} className="truncate text-[11px] text-[var(--lumi-text-tertiary)]">
                      {dup.feedTitle}
                      {dup.publishedAt != null && dup.publishedAt !== '' ? ` · ${dup.publishedAt.slice(0, 10)}` : ''}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          )
        })()}
      {/* 0011 Gate 3：移动端卡片化（<1024）；桌面行保持 0009
          密度（Spec R2：两套展示共存，CSS 分发） */}
      <div className="max-lg:px-2 max-lg:py-1">
        <div className="max-lg:hidden">
          <EntryRow
            item={item}
            selected={item.entryRef === selectedEntryRef}
            selectMode={selectMode}
            checked={selectedRefs.has(item.entryRef)}
            onToggleSelect={toggleSelect}
          />
        </div>
        <div className="lg:hidden">
          <EntryCard
            item={item}
            selected={item.entryRef === selectedEntryRef}
            selectMode={selectMode}
            checked={selectedRefs.has(item.entryRef)}
            onToggleSelect={toggleSelect}
          />
        </div>
      </div>
    </li>
  )

  // F016：对照阅读挂载时整列替换为双栏视图（关闭恢复原列表）
  if (compareRefs !== null) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <Suspense fallback={null}>
          <CompareRead
            refs={compareRefs}
            onClose={() => setCompareRefs(null)}
          />
        </Suspense>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ListHeader view={view} loadedCount={entries.length} />

      {/* F014：阅读预算面板（列表工具区；会话内临时清单） */}
      {budgetOpen && (
        <Suspense fallback={null}>
          <ReadingBudgetPanel
          candidates={budgetCandidates}
          onOpenEntry={(entryRef) => {
            openEntry(entryRef)
          }}
            onClose={() => setBudgetOpen(false)}
          />
        </Suspense>
      )}
      {/* N041：今日必读面板（服务端持久化队列 + 分段/冻结/间隔） */}
      {queueOpen && (
        <Suspense fallback={null}>
          <ReadingQueuePanel
            currentItemRef={selectedEntryRef}
            onOpenEntry={(entryRef) => {
              openEntry(entryRef)
            }}
            onClose={() => setQueueOpen(false)}
          />
        </Suspense>
      )}
      {/* F024：积压整理面板（预览→确认→执行；保护项服务端强制） */}
      {backlogOpen && (
        <Suspense fallback={null}>
          <BacklogPanel onClose={() => setBacklogOpen(false)} />
        </Suspense>
      )}
      {/* N037：断更恢复横幅（有待处理窗口才渲染） */}
      <Suspense fallback={null}>
        <RecoveryBanner />
      </Suspense>
      {/* N050：阅读路径面板（设备本地；恢复/停用/清空） */}
      {readingPathOpen && (
        <Suspense fallback={null}>
          <ReadingPathPanel
            onOpenEntry={(entryRef) => {
              openEntry(entryRef)
            }}
            onClose={() => setReadingPathOpen(false)}
          />
        </Suspense>
      )}
      {/* N047：收录撞车提示（定位/仍要加入；非阻断） */}
      <Suspense fallback={null}>
        <DuplicateWarningToast
          onLocate={(entryRef) => {
            openEntry(entryRef)
          }}
        />
      </Suspense>
      {/* F06 排序切换 + F07 多选入口（列表工具行；移动端也有——列表头
          仅桌面显示，这里是其唯一工具入口） */}
      <div className="flex flex-wrap items-center justify-end gap-1.5 border-b border-[var(--lumi-separator)] px-4 py-1">
        {/* F014：阅读预算入口 */}
        <button
          type="button"
          aria-pressed={budgetOpen}
          onClick={() => setBudgetOpen((v) => !v)}
          className={cx(
            'mr-auto flex min-h-7 items-center gap-1 rounded-[var(--lumi-radius-full)] px-2.5 py-1 text-xs transition-colors duration-[var(--lumi-motion-fast)]',
            'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
            budgetOpen
              ? 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]'
              : 'text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-text-secondary)]',
          )}
        >
          阅读预算
        </button>
        {/* N041：今日必读入口 */}
        <button
          type="button"
          aria-pressed={queueOpen}
          onClick={() => setQueueOpen((v) => !v)}
          className={cx(
            'mr-auto flex min-h-7 items-center gap-1 rounded-[var(--lumi-radius-full)] px-2.5 py-1 text-xs transition-colors duration-[var(--lumi-motion-fast)]',
            'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
            queueOpen
              ? 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]'
              : 'text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-text-secondary)]',
          )}
        >
          今日必读
        </button>
        {/* N050：阅读路径入口（设备本地） */}
        <button
          type="button"
          aria-pressed={readingPathOpen}
          onClick={() => setReadingPathOpen((v) => !v)}
          className={cx(
            'mr-auto flex min-h-7 items-center gap-1 rounded-[var(--lumi-radius-full)] px-2.5 py-1 text-xs transition-colors duration-[var(--lumi-motion-fast)]',
            'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
            readingPathOpen
              ? 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]'
              : 'text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-text-secondary)]',
          )}
        >
          阅读路径
        </button>
        {/* F024：积压整理入口 */}
        <button
          type="button"
          aria-pressed={backlogOpen}
          onClick={() => setBacklogOpen((v) => !v)}
          className={cx(
            'mr-auto flex min-h-7 items-center gap-1 rounded-[var(--lumi-radius-full)] px-2.5 py-1 text-xs transition-colors duration-[var(--lumi-motion-fast)]',
            'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
            backlogOpen
              ? 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]'
              : 'text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-text-secondary)]',
          )}
        >
          积压整理
        </button>
        {timelineOrder === 'oldest' && (
          <p
            role="note"
            data-testid="timeline-order-note"
            className="mr-auto text-xs text-[var(--lumi-text-tertiary)]"
          >
            最早优先（当前已加载范围内排序，服务端分页仍为最新优先）
          </p>
        )}
        {timelineOrder === 'received' && (
          <p
            role="note"
            data-testid="timeline-order-received-note"
            className="mr-auto text-xs text-[var(--lumi-text-tertiary)]"
          >
            按接收时间（服务端排序；页边界仍由上游分页决定）
          </p>
        )}
        <button
          type="button"
          data-testid="timeline-order-toggle"
          aria-pressed={timelineOrder !== 'newest'}
          title="切换时间线排序（最新优先 / 最早优先 / 按接收时间）"
          onClick={cycleTimelineOrder}
          className={cx(
            'rounded-[var(--lumi-radius-full)] px-2.5 py-1 text-xs transition-colors duration-[var(--lumi-motion-fast)]',
            'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
            timelineOrder === 'oldest'
              ? 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]'
              : 'text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-text-secondary)]',
          )}
        >
          {timelineOrder === 'newest'
            ? '最新优先'
            : timelineOrder === 'oldest'
              ? '最早优先'
              : '按接收时间'}
        </button>
        {/* F018：同链聚合开关 */}
        <button
          type="button"
          aria-pressed={aggregateOn}
          onClick={() => {
            setAggregateOn((v) => !v)
            setExpandedGroups(new Set())
          }}
          className={cx(
            'flex min-h-7 items-center gap-1 rounded-[var(--lumi-radius-full)] px-2.5 py-1 text-xs transition-colors duration-[var(--lumi-motion-fast)]',
            'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
            aggregateOn
              ? 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]'
              : 'text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-text-secondary)]',
          )}
        >
          聚合同链
        </button>
        {selectMode && selectedRefs.size === 2 && (
          <button
            type="button"
            data-testid="compare-open"
            onClick={() => {
              const [a, b] = [...selectedRefs]
              if (a !== undefined && b !== undefined) setCompareRefs([a, b])
            }}
            className="flex min-h-7 items-center gap-1 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-2.5 py-0.5 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            对照阅读
          </button>
        )}
        {selectMode ? (
          <button
            type="button"
            onClick={exitSelectMode}
            aria-label="退出多选"
            className="flex min-h-7 items-center gap-1 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-2.5 py-0.5 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            <X aria-hidden className="size-3.5" />
            退出选择
          </button>
        ) : (
          <button
            type="button"
            data-testid="enter-select-mode"
            aria-label="选择文章（进入多选）"
            onClick={() => setSelectMode(true)}
            className="flex min-h-7 items-center gap-1 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-2.5 py-0.5 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            <CheckSquare aria-hidden className="size-3.5" />
            选择
          </button>
        )}
      </div>

      {/* 0011 修正补充：折叠态隐藏列表内容（窄栏仅 header） */}
      <div
        ref={scrollContainerRef}
        data-testid="list-scroll-container"
        className="min-h-0 flex-1 overflow-y-auto"
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
      >
        {/* F09 下拉刷新指示区（刷新列表数据 = refetch，不触发上游抓取） */}
        {(pull !== null || refreshState !== 'idle') && (
          <div
            data-testid="pull-indicator"
            role="status"
            className="flex items-center justify-center gap-1.5 overflow-hidden py-1 text-xs text-[var(--lumi-text-tertiary)]"
            style={pull !== null ? { height: `${pull.offset}px`, paddingTop: 0, paddingBottom: 0 } : undefined}
          >
            <RotateCw
              aria-hidden
              className={cx(
                'size-3.5 shrink-0',
                (refreshState === 'refreshing' || (pull !== null && pull.offset > 0)) && 'animate-spin',
              )}
            />
            {refreshState === 'idle' &&
              (pull !== null
                ? pull.offset >= PULL_THRESHOLD_PX
                  ? '释放刷新列表'
                  : '下拉刷新列表'
                : '')}
            {refreshState === 'refreshing' && '刷新中…'}
            {refreshState === 'done' && '已刷新'}
            {refreshState === 'error' && '刷新失败'}
          </div>
        )}

        {/* 0011：卡片化后取消行分隔线（卡片自带圆角表面）；仍保留
            列表语义 ul/li（分组小节与滚动标记已读依赖）。 */}
        {isPending && (
          <div className="flex flex-col gap-3 p-4" aria-label="文章加载中">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="flex flex-col gap-1.5">
                <Skeleton className="h-3 w-2/5" />
                <Skeleton className="h-4 w-4/5" />
              </div>
            ))}
          </div>
        )}

        {isError && (
          <div className="p-4 text-sm text-[var(--lumi-danger)]" role="alert">
            <p>文章加载失败</p>
            <p className="mt-1 text-xs text-[var(--lumi-text-secondary)]">{error.message}</p>
            <Button
              size="sm"
              onClick={() => refetch()}
              className="mt-2 max-lg:w-full"
            >
              重试
            </Button>
          </div>
        )}

        {!isPending && !isError && entries.length === 0 && (
          <EmptyState
            icon={<Inbox />}
            title={EMPTY_TEXTS[view].title}
            description={EMPTY_TEXTS[view].description}
            className="h-full"
          />
        )}

        {entries.length > 0 && (
          <ul data-density={listDensity} className="max-lg:divide-none lg:divide-y lg:divide-[var(--lumi-separator)]">
            {listGroupByFeed ? (
              <>
                {/* F05：按来源分组（保持首次出现顺序；组头 sticky +
                    折叠 + 计数标注（已加载条数，非服务端总数）） */}
                {feedGroups.map((group) => {
                  const collapsed = collapsedFeeds.has(group.feedTitle)
                  return (
                    <Fragment key={group.feedTitle}>
                      <li className="sticky top-0 z-[1] bg-[var(--lumi-surface)] px-4 pb-1 pt-2.5">
                        <div className="flex min-w-0 items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-[var(--lumi-text-tertiary)]">
                          <button
                            type="button"
                            onClick={() => toggleFeedCollapse(group.feedTitle)}
                            aria-expanded={!collapsed}
                            aria-label={`折叠/展开「${group.feedTitle}」分组`}
                            className="flex min-h-6 min-w-0 items-center gap-1 rounded-[var(--lumi-radius-sm)] text-left focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                          >
                            <ChevronDown
                              aria-hidden
                              className={cx(
                                'size-3 shrink-0 transition-transform duration-[var(--lumi-motion-fast)]',
                                collapsed && '-rotate-90',
                              )}
                            />
                            <span className="truncate">{group.feedTitle}</span>
                          </button>
                          {/* 计数是「已加载」口径，绝不冒充服务端总数 */}
                          <span className="shrink-0 normal-case" data-loaded-count={group.items.length}>
                            已加载 {group.items.length} 条
                          </span>
                          <button
                            type="button"
                            disabled={group.feedUrl === null}
                            title={
                              group.feedUrl === null
                                ? '该来源缺少 feedUrl，无法过滤'
                                : `只看「${group.feedTitle}」`
                            }
                            onClick={() => {
                              if (group.feedUrl !== null) {
                                selectScope({ kind: 'rss-feed', feedUrl: group.feedUrl })
                              }
                            }}
                            className="shrink-0 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-1.5 py-0.5 text-[11px] normal-case transition-colors duration-[var(--lumi-motion-fast)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)] disabled:cursor-not-allowed disabled:opacity-50 enabled:hover:bg-[var(--lumi-surface-hover)] enabled:hover:text-[var(--lumi-text-secondary)]"
                          >
                            只看此来源
                          </button>
                        </div>
                      </li>
                      {!collapsed && group.items.map(renderRow)}
                    </Fragment>
                  )
                })}
                {!isPending && !isError && (
                  <SentinelState
                    sentinelRef={sentinelRef}
                    hasNextPage={hasNextPage}
                    isFetchingNextPage={isFetchingNextPage}
                  />
                )}
              </>
            ) : (
              (groupByDate ? groupEntriesByDate(entries) : [{ label: null, items: entries }]).map(
                (group) => (
                  <Fragment key={group.label ?? 'all'}>
                    {group.label !== null && (
                      <li
                        aria-hidden="true"
                        className="sticky top-0 z-[1] bg-[var(--lumi-surface)] px-4 pb-1 pt-2.5 text-[11px] font-medium uppercase tracking-wide text-[var(--lumi-text-tertiary)]"
                      >
                        {group.label}
                      </li>
                    )}
                    {group.items.map((item: EntryListItem) => renderRow(item))}
                    {/* 无限滚动哨兵（0011）：滚入视口自动拉下一页 */}
                    {!isPending && !isError && (
                      <SentinelState
                        sentinelRef={sentinelRef}
                        hasNextPage={hasNextPage}
                        isFetchingNextPage={isFetchingNextPage}
                      />
                    )}
                  </Fragment>
                ),
              )
            )}
          </ul>
        )}
      </div>

      {/* F07 批量操作栏（固定于列表底部；处理中禁用全部动作） */}
      {selectMode && (
        <div
          role="toolbar"
          aria-label="批量操作"
          data-testid="batch-bar"
          className="border-t border-[var(--lumi-separator)] bg-[var(--lumi-surface)] px-3 py-2"
          style={{ paddingBottom: 'max(0.5rem, var(--safe-bottom))' }}
        >
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-[var(--lumi-text-secondary)]" data-testid="selected-count">
              已选 {selectedRefs.size} 条
            </span>
            <button
              type="button"
              onClick={() => setSelectedRefs(new Set(entries.map((e) => e.entryRef)))}
              disabled={batchRunning}
              className="min-h-11 rounded-[var(--lumi-radius-md)] px-2 py-1 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              全选已加载
            </button>
            <button
              type="button"
              onClick={() => setSelectedRefs(new Set())}
              disabled={selectedRefs.size === 0 || batchRunning}
              className="min-h-11 rounded-[var(--lumi-radius-md)] px-2 py-1 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              清除
            </button>
            <span className="flex-1" />
            <button
              type="button"
              data-testid="ask-batch-open"
              disabled={selectedRefs.size === 0}
              onClick={() => setAskOpen(true)}
              className="min-h-11 rounded-[var(--lumi-radius-md)] px-2.5 py-1 text-xs font-medium text-[var(--lumi-accent-text)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              基于所选提问
            </button>
            {(['read', 'star', 'readLater'] as BatchKind[]).map((kind) => (
              <button
                key={kind}
                type="button"
                data-testid={`batch-${kind}`}
                disabled={batchRunning || overLimit || selectedRefs.size === 0}
                onClick={() => void runBatch(kind, [...selectedRefs])}
                className="min-h-11 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-accent-soft)] px-2.5 py-1 text-xs font-medium text-[var(--lumi-accent-text)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-accent-soft)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {BATCH_LABELS[kind]}
              </button>
            ))}
          </div>
          {overLimit && (
            <p role="alert" className="mt-1 text-xs text-[var(--lumi-danger)]">
              一次最多批量处理 {BATCH_LIMIT} 条，请减少选择后再操作。
            </p>
          )}
          {batchRunning && (
            <p role="status" className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">
              处理中…（逐条提交，请勿离开）
            </p>
          )}
          {batch !== null && !batch.running && batch.failed.length > 0 && (
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <p
                role="alert"
                data-testid="batch-failed"
                className="min-w-0 flex-1 truncate text-xs text-[var(--lumi-danger)]"
                title={batch.failed.join('、')}
              >
                {BATCH_LABELS[batch.kind]}失败 {batch.failed.length} 条：{batch.failed.join('、')}
              </p>
              <button
                type="button"
                data-testid="batch-retry"
                onClick={() => void runBatch(batch.kind, batch.failed)}
                className="min-h-11 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
              >
                重试失败项
              </button>
            </div>
          )}
        </div>
      )}
      {/* F065：多篇共同问答（范围=当前多选；可移除；引用 chips 打开该文）。
          条件挂载：open-prop 门控的 lazy 仍会首帧拉 chunk——条件挂载后
          首帧完全不参与（bundle guard 契约）。 */}
      {askOpen && (
        <Suspense fallback={null}>
          <AskBatchDialog
            open={askOpen}
            onClose={() => setAskOpen(false)}
            targets={entries
              .filter((item) => selectedRefs.has(item.entryRef))
              .map((item) => ({ ref: item.entryRef, title: item.title }))}
            onRemove={(ref) => {
              setSelectedRefs((prev) => {
                const next = new Set(prev)
                next.delete(ref)
                return next
              })
            }}
          />
        </Suspense>
      )}
    </div>
  )
}
