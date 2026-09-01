/** SubscriptionsPage — 订阅中心（0011 Gate 4 → 0013 Gate 3 演进）。
 *
 * 0013 Gate 3：真实 FreshRSS category grouping（管理视角，取代 0011 的
 * 「单一未分组」旧假设——BFF /api/v1/subscriptions 早已携带真实分类）：
 * - 分类与 Feed 全部来自 FreshRSS server truth（useSubscriptions /
 *   useCategories），不硬编码任何分类名；无分类 feed → 真实「未分组」；
 * - 本地搜索（客户端过滤当前列表，文案诚实，非全局搜索）；
 * - Feed 行保持 Lumi Mist：icon / title / domain / ⋯（不堆常驻按钮）：
 *   ⋯ → 移动到分类（含新建分类）/ 取消订阅（破坏性双重确认）；
 * - 分类行 ⋯ → 重命名分类；新建分类入口在「移动到分类」对话框内
 *   （FreshRSS 唯一 create-category 通道是移动时自动创建）；
 * - mutation 一律 server-confirmed → invalidate（feeds/categories/
 *   subscriptions/entries），与侧栏同一 truth，无第二套本地缓存；
 * - scope reconciliation：取消订阅后当前 rss-feed scope 失效、重命名
 *   后旧 categoryId 失效 → 自动回退「全部」；
 * - 拖拽手柄不显示（无持久化排序契约）；OPML 导入真实可用（Gate 4：
 *   OpmlImportDialog，严格 preview → confirm → result）。
 *
 * 点 feed 主区域 → selectScope + section 回首页（与侧栏导航同一语义）。 */

import { useEffect, useMemo, useState } from 'react'
import { ChevronDown, MoreHorizontal, Rss, Search, Upload } from 'lucide-react'
import { useCategories, useSubscriptions } from '../../api/queries'
import type { Subscription } from '../../api/types'
import { useReaderUi, ALL_SCOPE } from '../../store/reader-ui'
import AddSubscriptionDialog from '../AddSubscriptionDialog'
import OpmlImportDialog from '../OpmlImportDialog'
import MoveSubscriptionDialog from '../MoveSubscriptionDialog'
import RenameCategoryDialog from '../RenameCategoryDialog'
import UnsubscribeDialog from '../UnsubscribeDialog'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Menu } from '../ui/Menu'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'

/** 分类分组节点：真实分类（category.id）或「未分组」。 */
interface SubscriptionGroup {
  key: string // category.id 或 'ungrouped'
  label: string
  subscriptions: Subscription[]
}

/** 真实分组：subscription.category（无 → 未分组，排最后，其余按 label
 * 稳定排序）。禁止硬编码分类名——全部来自 FreshRSS。 */
function groupByCategory(subscriptions: Subscription[]): SubscriptionGroup[] {
  const byKey = new Map<string, SubscriptionGroup>()
  for (const subscription of subscriptions) {
    const category =
      subscription.category &&
      typeof subscription.category.id === 'string' &&
      subscription.category.id
        ? subscription.category
        : null
    if (category !== null) {
      const node = byKey.get(category.id)
      if (node) node.subscriptions.push(subscription)
      else
        byKey.set(category.id, {
          key: category.id,
          label: category.label || category.id,
          subscriptions: [subscription],
        })
    } else {
      const node = byKey.get('ungrouped')
      if (node) node.subscriptions.push(subscription)
      else
        byKey.set('ungrouped', {
          key: 'ungrouped',
          label: '未分组',
          subscriptions: [subscription],
        })
    }
  }
  const groups = [...byKey.values()]
  groups.sort((a, b) => {
    if (a.key === 'ungrouped') return 1
    if (b.key === 'ungrouped') return -1
    return a.label.localeCompare(b.label, 'zh-CN')
  })
  return groups
}

/** feedUrl → 展示域名（解析失败原样返回 URL，不伪造）。 */
function domainOf(feedUrl: string): string {
  try {
    return new URL(feedUrl).hostname
  } catch {
    return feedUrl
  }
}

export default function SubscriptionsPage() {
  const subscriptions = useSubscriptions()
  const categories = useCategories(true)

  const selectScope = useReaderUi((s) => s.selectScope)
  const selectView = useReaderUi((s) => s.selectView)
  const selectSection = useReaderUi((s) => s.selectSection)
  const scope = useReaderUi((s) => s.scope)

  // 本地过滤（仅当前已加载的订阅——客户端过滤，非全局搜索）
  const [query, setQuery] = useState('')
  // 收起集合（管理视角默认全展开；只记收起的组）
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set())
  // 0013 Gate 2：添加订阅入口；Gate 4：OPML 导入入口
  const [addOpen, setAddOpen] = useState(false)
  const [opmlOpen, setOpmlOpen] = useState(false)
  // 0013 Gate 3：管理对话框目标（null = 关闭）
  const [moveTarget, setMoveTarget] = useState<Subscription | null>(null)
  const [unsubscribeTarget, setUnsubscribeTarget] = useState<Subscription | null>(null)
  const [renameTarget, setRenameTarget] = useState<{ id: string; label: string } | null>(null)

  const filtered = useMemo(() => {
    const all = subscriptions.data ?? []
    const q = query.trim().toLowerCase()
    if (!q) return all
    return all.filter(
      (s) =>
        s.title.toLowerCase().includes(q) ||
        s.feedUrl.toLowerCase().includes(q) ||
        (s.category?.label.toLowerCase().includes(q) ?? false),
    )
  }, [subscriptions.data, query])

  const groups = useMemo(() => groupByCategory(filtered), [filtered])

  // scope reconciliation（Gate 3）：mutation → invalidate → server truth
  // 更新后，清掉指向已删除 feed / 已重命名旧 categoryId 的 stale scope，
  // 回退「全部」。数据未加载完成时跳过（避免误清）。
  useEffect(() => {
    const subs = subscriptions.data
    if (subs === undefined) return
    if (scope.kind === 'rss-feed') {
      if (!subs.some((s) => s.feedUrl === scope.feedUrl)) {
        selectScope(ALL_SCOPE)
      }
    } else if (scope.kind === 'rss-category') {
      const cats = categories.data
      if (cats !== undefined && !cats.some((c) => c.id === scope.categoryId)) {
        selectScope(ALL_SCOPE)
      }
    }
  }, [subscriptions.data, categories.data, scope, selectScope])

  const toggleGroup = (key: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  if (subscriptions.isPending) {
    return (
      <div className="flex flex-1 flex-col gap-3 p-4" aria-label="订阅加载中">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-14 w-full" />
        ))}
      </div>
    )
  }

  if (subscriptions.isError) {
    return (
      <div className="p-4 text-sm text-[var(--lumi-danger)]" role="alert">
        <p>订阅加载失败</p>
        <p className="mt-1 text-xs text-[var(--lumi-text-secondary)]">
          {subscriptions.error.message}
        </p>
        <Button size="sm" onClick={() => subscriptions.refetch()} className="mt-2">
          重试
        </Button>
      </div>
    )
  }

  const total = subscriptions.data?.length ?? 0

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <AddSubscriptionDialog open={addOpen} onClose={() => setAddOpen(false)} />
      <OpmlImportDialog open={opmlOpen} onClose={() => setOpmlOpen(false)} />
      <MoveSubscriptionDialog
        open={moveTarget !== null}
        onClose={() => setMoveTarget(null)}
        subscription={moveTarget}
      />
      <UnsubscribeDialog
        open={unsubscribeTarget !== null}
        onClose={() => setUnsubscribeTarget(null)}
        subscription={unsubscribeTarget}
      />
      <RenameCategoryDialog
        open={renameTarget !== null}
        onClose={() => setRenameTarget(null)}
        category={renameTarget}
      />
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

        {/* 顶部动作：添加 RSS（Gate 2）/ OPML 导入（Gate 4）真实可用 */}
        <div className="mb-3 flex flex-wrap gap-2" role="group" aria-label="订阅管理动作">
          <Button
            variant="secondary"
            onClick={() => setAddOpen(true)}
            aria-haspopup="dialog"
            className="text-xs"
          >
            <Rss aria-hidden className="size-3.5" />
            添加 RSS
          </Button>
          <Button
            variant="secondary"
            onClick={() => setOpmlOpen(true)}
            aria-haspopup="dialog"
            className="text-xs"
          >
            <Upload aria-hidden className="size-3.5" />
            导入 OPML
          </Button>
        </div>

        {/* 真实分类分组（全部来自 FreshRSS；无硬编码分类名） */}
        {total === 0 ? (
          <EmptyState
            icon={<Rss aria-hidden className="size-8" />}
            title="还没有订阅源"
            description="点击「添加 RSS」订阅第一个源。"
          />
        ) : (
          <div className="flex flex-col gap-2">
            {groups.length === 0 && (
              <EmptyState
                icon={<Search aria-hidden className="size-8" />}
                title="没有匹配的订阅源"
                description="换个关键词试试。"
              />
            )}
            {groups.map((group) => {
              const expanded = !collapsedGroups.has(group.key)
              const isUngrouped = group.key === 'ungrouped'
              return (
                <div
                  key={group.key}
                  className="overflow-hidden rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]"
                >
                  {/* 分类行：disclosure（主区域）+ ⋯ 分类操作（真实分类） */}
                  <div className="flex items-center">
                    <button
                      type="button"
                      onClick={() => toggleGroup(group.key)}
                      aria-expanded={expanded}
                      aria-controls={`subscriptions-group-${encodeURIComponent(group.key)}`}
                      aria-label={`${group.label}，${group.subscriptions.length} 个订阅源`}
                      className="flex min-h-11 flex-1 items-center gap-2 px-3.5 py-2 text-left"
                    >
                      <ChevronDown
                        aria-hidden
                        className={cx(
                          'size-4 text-[var(--lumi-text-tertiary)] transition-transform duration-[var(--lumi-motion-fast)]',
                          !expanded && '-rotate-90',
                        )}
                      />
                      <span className="text-sm font-medium text-[var(--lumi-text-primary)]">
                        {group.label}
                      </span>
                      <span className="text-xs text-[var(--lumi-text-tertiary)]">
                        {group.subscriptions.length}
                      </span>
                    </button>
                    {!isUngrouped && (
                      <Menu
                        trigger={({ triggerProps }) => (
                          <button
                            {...triggerProps}
                            aria-label={`「${group.label}」分类操作`}
                            className={cx(
                              'mr-2 flex size-8 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)]',
                              'text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)]',
                              'hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
                              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                            )}
                          >
                            <MoreHorizontal aria-hidden className="size-4" />
                          </button>
                        )}
                        items={[
                          { key: 'rename', content: '重命名分类' },
                        ]}
                        onSelect={() =>
                          setRenameTarget({ id: group.key, label: group.label })
                        }
                      />
                    )}
                  </div>

                  {expanded && (
                    <ul
                      id={`subscriptions-group-${encodeURIComponent(group.key)}`}
                      className="divide-y divide-[var(--lumi-separator)] border-t border-[var(--lumi-separator)]"
                    >
                      {group.subscriptions.map((subscription) => (
                        <li key={subscription.subscriptionRef} className="flex items-center">
                          {/* 主区域：icon / title / domain（Lumi Mist 行） */}
                          <button
                            type="button"
                            onClick={() => {
                              // 与侧栏 feed 导航同一语义：切回首页 + scope
                              selectSection('home')
                              selectView('all')
                              selectScope({ kind: 'rss-feed', feedUrl: subscription.feedUrl })
                            }}
                            className={cx(
                              'flex min-h-14 min-w-0 flex-1 items-center gap-3 px-3.5 py-2.5 text-left',
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
                              <span
                                className="block truncate text-sm font-medium text-[var(--lumi-text-primary)]"
                                title={subscription.title}
                              >
                                {subscription.title}
                              </span>
                              <span
                                className="block truncate text-xs text-[var(--lumi-text-tertiary)]"
                                title={subscription.feedUrl}
                              >
                                {domainOf(subscription.feedUrl)}
                              </span>
                            </span>
                          </button>
                          {/* ⋯ Feed 操作菜单（不堆常驻按钮） */}
                          <Menu
                            trigger={({ triggerProps }) => (
                              <button
                                {...triggerProps}
                                aria-label={`「${subscription.title}」的操作`}
                                className={cx(
                                  'mr-2 flex size-8 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)]',
                                  'text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)]',
                                  'hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
                                  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                                )}
                              >
                                <MoreHorizontal aria-hidden className="size-4" />
                              </button>
                            )}
                            items={[
                              { key: 'move', content: '移动到分类' },
                              { key: 'unsubscribe', content: '取消订阅' },
                            ]}
                            onSelect={(key) => {
                              if (key === 'move') setMoveTarget(subscription)
                              else if (key === 'unsubscribe') setUnsubscribeTarget(subscription)
                            }}
                          />
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
