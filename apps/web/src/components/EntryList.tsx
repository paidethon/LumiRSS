import { Inbox, Loader2, PanelLeftClose } from 'lucide-react'
import { Fragment, useEffect, useMemo, useRef } from 'react'
import { useEntries, useEntryStateMutation } from '../api/queries'
import type { EntryView } from '../api/types'
import { useReaderUi } from '../store/reader-ui'
import { useAppSettings } from '../store/app-settings'
import { groupEntriesByDate } from '../lib/entry-groups'
import { matchesFilterRules } from './settings/FilterRulesPage'
import EntryCard from './EntryCard'
import EntryRow from './EntryRow'
import { Button } from './ui/Button'
import { EmptyState } from './ui/EmptyState'
import { Skeleton } from './ui/Skeleton'

const VIEW_TITLES: Record<EntryView, string> = {
  all: 'All',
  unread: 'Unread',
  starred: 'Starred',
}

const EMPTY_TEXTS: Record<EntryView, { title: string; description: string }> = {
  all: { title: '这里还没有文章', description: '订阅源还没有内容，稍后再来看看。' },
  unread: { title: '没有未读文章', description: '全部读完了，干得漂亮。' },
  starred: { title: '还没有收藏文章', description: '阅读时点击「收藏」，文章会出现在这里。' },
}

export default function EntryList() {
  const view = useReaderUi((s) => s.view)
  const selectedFeedUrl = useReaderUi((s) => s.selectedFeedUrl)
  const selectedEntryRef = useReaderUi((s) => s.selectedEntryRef)
  // 0010 Gate C：折叠入口（桌面 lg；移动端隐藏）
  const updateSettings = useAppSettings((s) => s.update)
  // 0010a Gate E（AC7）：按日期分组
  const groupByDate = useAppSettings((s) => s.settings.groupByDate)
  // 0010a Gate E（AC9）：实验性滚动标记已读（默认关）
  const scrollMarkUnread = useAppSettings((s) => s.settings.scrollMarkUnread)
  // 0010a Gate F（AC24）：显示层过滤（全局规则，BFF 层 planned·0013）
  const filterRules = useAppSettings((s) => s.settings.filterRules)
  const filterEnabled = filterRules.some((r) => r.enabled)

  const feedsTitle = useEntries(view, selectedFeedUrl)
  const { data, isPending, isError, error, refetch } = feedsTitle
  // useMemo：data 引用稳定时 entries 引用也稳定（避免 effect 依赖每渲染变化）
  // 0010a F3：显示层过滤（仅标题匹配全局启用规则，feedId=null）
  const entries = useMemo(() => {
    const all = data?.pages.flatMap((page) => page.items) ?? []
    if (!filterEnabled) return all
    return all.filter((item) => matchesFilterRules(item.title, filterRules, null) === null)
  }, [data, filterEnabled, filterRules])
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

  // ---- 滚动标记已读（AC9）：IntersectionObserver + 保守策略 ----
  const { mutate: markReadMutate } = useEntryStateMutation()
  // entryRef → <li> 元素（observer 观察目标）
  const rowRefs = useRef(new Map<string, HTMLLIElement>())
  // 最新 read 状态（observer 回调闭包里读，避免过期）
  const readState = useRef(new Map<string, boolean>())
  // 曾进入视口的条目（初始加载时视口下方的不算）；已派发标记的条目（防重复）
  const seen = useRef(new Set<string>())
  const dispatched = useRef(new Set<string>())

  useEffect(() => {
    readState.current = new Map(entries.map((e) => [e.entryRef, e.read]))
  }, [entries])

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

  useEffect(() => {
    const rows = rowRefs.current
    if (!scrollMarkUnread || rows.size === 0) return
    const observer = new IntersectionObserver(
      (records) => {
        for (const r of records) {
          const ref = (r.target as HTMLElement).dataset.entryRowRef
          if (!ref) continue
          if (r.isIntersecting) {
            seen.current.add(ref)
          } else if (
            // 完全滚出上方才算读完（滚到下方的尚未读）
            r.boundingClientRect.bottom < 0 &&
            seen.current.has(ref) &&
            !dispatched.current.has(ref) &&
            readState.current.get(ref) === false
          ) {
            dispatched.current.add(ref)
            markReadMutate({ entryRef: ref, patch: { read: true } })
          }
        }
      },
      // 需要知道「离开」时机：默认阈值 0 会在完全离开时回调一次
    )
    for (const el of rows.values()) observer.observe(el)
    return () => observer.disconnect()
  }, [scrollMarkUnread, entries, markReadMutate])

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex items-center gap-2 border-b border-[var(--lumi-separator)] px-4 py-2.5">
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-[var(--lumi-text-primary)]">
            {VIEW_TITLES[view]}
          </h2>
          <p className="text-xs text-[var(--lumi-text-tertiary)]">已加载 {entries.length} 条</p>
        </div>
        <button
          type="button"
          onClick={() => updateSettings({ timelineCollapsed: true })}
          aria-label="折叠文章列表"
          className="hidden size-7 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)] lg:flex"
        >
          <PanelLeftClose aria-hidden className="size-4 rotate-180" />
        </button>
      </header>

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
            icon={<Inbox />}
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
