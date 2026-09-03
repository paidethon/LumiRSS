import { Inbox, Clock, Loader2, PanelLeft, PanelLeftClose } from 'lucide-react'
import { Fragment, useEffect, useMemo, useRef } from 'react'
import { useEntries, useEntryStateMutation, useFeeds } from '../api/queries'
import { useReadLater } from '../store/read-later'
import type { UiView } from '../lib/read-later'
import { useReaderUi } from '../store/reader-ui'
import { scopeTitle } from '../lib/navigation'
import { useAppSettings } from '../store/app-settings'
import { groupEntriesByDate } from '../lib/entry-groups'
import { matchesFilterRules } from './settings/FilterRulesPage'
import EntryCard from './EntryCard'
import EntryRow from './EntryRow'
import { Button } from './ui/Button'
import { EmptyState } from './ui/EmptyState'
import { Skeleton } from './ui/Skeleton'

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

export default function EntryList() {
  const view = useReaderUi((s) => s.view)
  const scope = useReaderUi((s) => s.scope)
  const selectedEntryRef = useReaderUi((s) => s.selectedEntryRef)
  // 0010 Gate C：折叠入口（桌面 lg；移动端隐藏）。0011 修正补充：
  // 放大/缩小同一按钮双向切换（图标随状态翻转），折叠后不再在
  // App 层弹出一个专门的展开按钮。
  const updateSettings = useAppSettings((s) => s.update)
  const timelineCollapsed = useAppSettings((s) => s.settings.timelineCollapsed)
  // 0010a Gate E（AC7）：按日期分组
  const groupByDate = useAppSettings((s) => s.settings.groupByDate)
  // 0010a Gate E（AC9）：实验性滚动标记已读（默认关）
  const scrollMarkUnread = useAppSettings((s) => s.settings.scrollMarkUnread)
  // 0010a Gate F（AC24）：显示层过滤（全局规则，BFF 层 planned·0013）
  const filterRules = useAppSettings((s) => s.settings.filterRules)
  const filterEnabled = filterRules.some((r) => r.enabled)

  // read-later marker 订阅（0011 修正补充：客户端过滤 §26）
  const readLaterItems = useReadLater((s) => s.items)
  const readLaterRefs = useMemo(() => new Set(readLaterItems.map((it) => it.entryRef)), [readLaterItems])

  // feed scope 的列表头标题：用 feeds 数据补全真实 feed 名（§9）
  const feeds = useFeeds()
  const feedsTitle = useEntries(scope, view)
  const { data, isPending, isError, error, refetch } = feedsTitle
  // useMemo：data 引用稳定时 entries 引用也稳定（避免 effect 依赖每渲染变化）
  // 0010a F3：显示层过滤（仅标题匹配全局启用规则，feedId=null）
  // 0011 修正补充：read-later 视图 = 全量拉取后客户端过滤（API 层已
  // 翻译为 view=all）——加入不移除（§26）；移除立即从列表消失（store
  // 订阅驱动重新过滤）。
  const entries = useMemo(() => {
    const all = data?.pages.flatMap((page) => page.items) ?? []
    const byRules = filterEnabled
      ? all.filter((item) => matchesFilterRules(item.title, filterRules, null) === null)
      : all
    if (view !== 'read-later') return byRules
    return byRules.filter((item) => readLaterRefs.has(item.entryRef))
  }, [data, filterEnabled, filterRules, view, readLaterRefs])
  const hasNextPage = feedsTitle.hasNextPage
  const isFetchingNextPage = feedsTitle.isFetchingNextPage
  const fetchNextPage = feedsTitle.fetchNextPage

  // ---- 无限滚动（0011：替换「加载更多」按钮，用户指令） ----
  // 哨兵 li 滚入视口 → 自动 fetchNextPage；IntersectionObserver 仅在
  // hasNextPage 且未在拉取时触发（拉取完成后 entries 变化重新观察）。
  const sentinelRef = useRef<HTMLLIElement>(null)
  useEffect(() => {
    const sentinel = sentinelRef.current
    if (!sentinel || !hasNextPage || isFetchingNextPage) return
    let observer: IntersectionObserver | null = null
    observer = new IntersectionObserver(
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
  }, [hasNextPage, isFetchingNextPage, fetchNextPage, entries])

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
              // 0017：离开视口后短暂停顿确认，期间滚回则取消（快速
              // 甩动经过的文章仍会被标记，但留出误触撤回窗口）
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

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* 桌面列表头（0011 §22/§24：移动端整行删除——scope 已由 MobileHeader
          承载，已加载 N 条无产品价值；仅 ≥1024 渲染）。
          标题 = scope 标题 + 视图后缀（如「RSS 订阅 · 未读」）。 */}
      <header className="hidden items-center gap-2 border-b border-[var(--lumi-separator)] px-4 py-2.5 lg:flex">
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-[var(--lumi-text-primary)]">
            {scope.kind === 'rss-feed'
              ? (feeds.data?.find((f) => f.feedUrl === scope.feedUrl)?.title ?? '订阅源')
              : scopeTitle(scope)}
            {view === 'unread' && <span className="ml-1.5 font-normal text-[var(--lumi-text-tertiary)]">· 未读</span>}
            {view === 'read-later' && <span className="ml-1.5 font-normal text-[var(--lumi-text-tertiary)]">· 稍后读</span>}
          </h2>
          <p className="text-xs text-[var(--lumi-text-tertiary)]">已加载 {entries.length} 条</p>
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

      {/* 0011 修正补充：折叠态隐藏列表内容（窄栏仅 header） */}
      <div className="min-h-0 flex-1 overflow-y-auto">
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
            icon={view === 'read-later' ? <Clock /> : <Inbox />}
            title={EMPTY_TEXTS[view].title}
            description={EMPTY_TEXTS[view].description}
            className="h-full"
          />
        )}

        {entries.length > 0 && (
          <ul className="max-lg:divide-none lg:divide-y lg:divide-[var(--lumi-separator)]">
            {(groupByDate ? groupEntriesByDate(entries) : [{ label: null, items: entries }]).map(
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
                  {group.items.map((item) => (
                    <li
                      key={item.entryRef}
                      data-entry-row-ref={item.entryRef}
                      ref={(el) => {
                        if (el) rowRefs.current.set(item.entryRef, el)
                        else rowRefs.current.delete(item.entryRef)
                      }}
                    >
                      {/* 0011 Gate 3：移动端卡片化（<1024）；桌面行保持 0009
                          密度（Spec R2：两套展示共存，CSS 分发） */}
                      <div className="max-lg:px-2 max-lg:py-1">
                        <div className="max-lg:hidden">
                          <EntryRow item={item} selected={item.entryRef === selectedEntryRef} />
                        </div>
                        <div className="lg:hidden">
                          <EntryCard item={item} selected={item.entryRef === selectedEntryRef} />
                        </div>
                      </div>
                    </li>
                  ))}
                  {/* 无限滚动哨兵（0011：替换「加载更多」按钮）：滚入视口
                      自动拉下一页；拉取中显示转圈指示；到底显示终态文案 */}
                  {!isPending && !isError && entries.length > 0 && (
                    <li
                      ref={sentinelRef}
                      aria-hidden={hasNextPage || isFetchingNextPage ? undefined : 'true'}
                      className="flex items-center justify-center py-4 max-md:pb-[84px]"
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
                  )}
                </Fragment>
              ),
            )}
          </ul>
        )}
      </div>
    </div>
  )
}
