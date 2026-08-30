/** SubscriptionsPage — 订阅页（0011 Gate 4，参考图 04-subscriptions）。
 *
 * 真实只读能力（useFeeds）+ 本地过滤搜索框：
 * - 搜索框只过滤「当前已加载的订阅源列表」（客户端过滤，文案诚实，
 *   非全局搜索）；
 * - feed 行：统一 RSS 图标（无 favicon 契约，不从不可信页面抓图）+
 *   真实标题 + feedUrl（description 无契约不伪造）；
 * - 无未读数契约 → 不显示数量徽标；
 * - 添加 RSS / OPML 导入 / 分组管理：禁用 + `0013` 徽标
 *   （订阅 CRUD 属 Unified Subscription Center，Spec §7.3）；
 * - 拖拽手柄不显示（无持久化排序契约）；
 * - Feed 契约无分类字段 → 单一真实「未分组」折叠组（默认展开，
 *   与侧栏 disclosure 的「默认收起」区分：订阅页是管理视角，
 *   参考图 04 的分组列表默认展开）。
 *
 * 点 feed → selectFeed + section 回首页（与侧栏导航同一语义，AC4）。 */

import { useMemo, useState } from 'react'
import { ChevronDown, Rss, Search } from 'lucide-react'
import { useFeeds } from '../../api/queries'
import { useReaderUi } from '../../store/reader-ui'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'

/** 顶部动作行：全部禁用 + 0013 徽标（订阅 CRUD 属 Unified
 * Subscription Center；诚实原则——不渲染可点击的假按钮）。 */
function PlannedAction({
  icon,
  label,
}: {
  icon: React.ReactNode
  label: string
}) {
  return (
    <div
      aria-disabled="true"
      title="订阅管理将在 0013 Unified Subscription Center 提供"
      className={cx(
        'flex cursor-default items-center gap-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)]',
        'px-2.5 py-2 text-xs text-[var(--lumi-text-tertiary)] opacity-70',
      )}
    >
      {icon}
      <span>{label}</span>
      <span className="ml-1 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[10px] font-medium">
        0013
      </span>
    </div>
  )
}

export default function SubscriptionsPage() {
  const feeds = useFeeds()
  const selectScope = useReaderUi((s) => s.selectScope)
  const selectView = useReaderUi((s) => s.selectView)
  const selectSection = useReaderUi((s) => s.selectSection)

  // 本地过滤（仅当前已加载的订阅源——客户端过滤，非全局搜索）
  const [query, setQuery] = useState('')
  const [groupExpanded, setGroupExpanded] = useState(true)

  const filtered = useMemo(() => {
    const all = feeds.data ?? []
    const q = query.trim().toLowerCase()
    if (!q) return all
    return all.filter(
      (f) =>
        f.title.toLowerCase().includes(q) ||
        f.feedUrl.toLowerCase().includes(q),
    )
  }, [feeds.data, query])

  if (feeds.isPending) {
    return (
      <div className="flex flex-1 flex-col gap-3 p-4" aria-label="订阅加载中">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-14 w-full" />
        ))}
      </div>
    )
  }

  if (feeds.isError) {
    return (
      <div className="p-4 text-sm text-[var(--lumi-danger)]" role="alert">
        <p>订阅加载失败</p>
        <p className="mt-1 text-xs text-[var(--lumi-text-secondary)]">
          {feeds.error.message}
        </p>
        <Button size="sm" onClick={() => feeds.refetch()} className="mt-2">
          重试
        </Button>
      </div>
    )
  }

  const total = feeds.data?.length ?? 0

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto p-3 max-md:pb-[76px]">
        {/* 搜索订阅源（本地过滤，文案诚实） */}
        <div className="relative mb-3">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--lumi-text-tertiary)]"
          />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索订阅源（当前列表）"
            aria-label="搜索订阅源"
            className={cx(
              'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
              'py-2.5 pl-9 pr-3 text-sm text-[var(--lumi-text-primary)]',
              'placeholder:text-[var(--lumi-text-tertiary)]',
              'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
            )}
          />
        </div>

        {/* 顶部动作：全部禁用 + 0013 徽标 */}
        <div className="mb-3 flex flex-wrap gap-2" role="group" aria-label="订阅管理动作">
          <PlannedAction icon={<Rss aria-hidden className="size-3.5" />} label="添加 RSS" />
          <PlannedAction icon={<Rss aria-hidden className="size-3.5" />} label="OPML 导入" />
          <PlannedAction icon={<Rss aria-hidden className="size-3.5" />} label="分组管理" />
        </div>

        {/* 唯一真实分组：未分组（无分类契约，禁止编造） */}
        <div className="overflow-hidden rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]">
          <button
            type="button"
            onClick={() => setGroupExpanded((v) => !v)}
            aria-expanded={groupExpanded}
            aria-controls="subscriptions-ungrouped"
            className="flex min-h-11 w-full items-center gap-2 px-3.5 py-2 text-left"
          >
            <Rss aria-hidden className="size-4 text-[var(--lumi-text-tertiary)]" />
            <span className="text-sm font-medium text-[var(--lumi-text-primary)]">未分组</span>
            <span className="text-xs text-[var(--lumi-text-tertiary)]">
              {filtered.length}
              {query.trim() && total > 0 ? ` / ${total}` : ''}
            </span>
            <ChevronDown
              aria-hidden
              className={cx(
                'ml-auto size-4 text-[var(--lumi-text-tertiary)] transition-transform duration-[var(--lumi-motion-fast)]',
                groupExpanded && 'rotate-180',
              )}
            />
          </button>

          {groupExpanded && (
            <ul id="subscriptions-ungrouped" className="divide-y divide-[var(--lumi-separator)]">
              {filtered.length === 0 ? (
                <li>
                  <EmptyState
                    icon={<Search aria-hidden className="size-8" />}
                    title={total === 0 ? '还没有订阅源' : '没有匹配的订阅源'}
                    description={total === 0 ? '通过 FreshRSS 添加订阅后，会显示在这里。' : '换个关键词试试。'}
                  />
                </li>
              ) : (
                filtered.map((feed) => (
                  <li key={feed.feedUrl}>
                    <button
                      type="button"
                      onClick={() => {
                        // 与侧栏 feed 导航同一语义（AC4）：切回首页 + scope
                        selectSection('home')
                        selectView('all')
                        selectScope({ kind: 'rss-feed', feedUrl: feed.feedUrl })
                      }}
                      className={cx(
                        'flex min-h-14 w-full items-center gap-3 px-3.5 py-2.5 text-left',
                        'transition-colors duration-[var(--lumi-motion-fast)]',
                        'hover:bg-[var(--lumi-surface-hover)] active:bg-[var(--lumi-surface-pressed)]',
                        'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                      )}
                    >
                      {/* 统一 RSS 图标（无 favicon 契约，不抓取外部图片） */}
                      <span
                        aria-hidden
                        className="flex size-9 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-selected)] text-[var(--lumi-accent)]"
                      >
                        <Rss className="size-4" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-[var(--lumi-text-primary)]" title={feed.title}>
                          {feed.title}
                        </span>
                        <span className="block truncate text-xs text-[var(--lumi-text-tertiary)]" title={feed.feedUrl}>
                          {feed.feedUrl}
                        </span>
                      </span>
                    </button>
                  </li>
                ))
              )}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
