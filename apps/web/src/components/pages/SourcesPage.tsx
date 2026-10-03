/** SourcesPage — 统一内容来源管理中心（R02）。
 *
 * 八类内容来源（+ RSSHub 路由，共九类）按 nav-registry 的
 * sourceTypeSourceOrder() 同序一行一类：真实数量、状态、最近更新、
 * 主操作全部来自 GET /api/v1/sources/summary（owning store 本地读取，
 * 零上游调用）。状态严格区分「服务未配置」（not_configured）与「集合
 * 为空」（empty）——前者引导接入，后者只是还没内容：
 *
 *   rss        → 订阅中心（subscriptions section）
 *   rsshub     → 添加来源对话框 RSSHub 模式（AddSourceDialog RssHubTab）
 *   api_source → 设置 · API 来源（settings-bridge 直达分类；该域的
 *                来源详情/管理面就在那里，不建第二套）
 *   newsletter → 设置 · 邮件（管理连接；简报内容页由后续迭代承接，
 *                本页不占位假入口）
 *   inbox      → 收件箱 section
 *   obsidian   → Obsidian 库 section
 *   bookmark / clip / snapshot → 各自集合 section（侧栏同名入口同源）
 *
 * 过滤统一在一行 Toolbar：搜索 + 类型 + 状态（ActionMenu 原语）。
 * 本页是只读总览 + 深链（管理留在各来源自己的控制面）；没有批量
 * 破坏性操作，高级接入运维工具（自动接入向导等）不进中心页。
 * 注册表未知类型（未来新增）按原样追加渲染（无深链），不假设类型
 * 集合封闭。
 *
 * 底栏「来源」tab 与桌面侧栏「来源」都导航到本页（AppSection sources）。
 */

import { Suspense, lazy, useMemo, useState } from 'react'
import { Radio, Search, SlidersHorizontal, Layers, Plus } from 'lucide-react'
import { useSourcesSummary } from '../../api/queries'
import type { SourceTypeSummary } from '../../api/client'
import { useReaderUi } from '../../store/reader-ui'
import type { AppSection } from '../../store/reader-ui'
import { requestOpenSettings } from '../settings/settings-bridge'
import {
  NAV_ENTRIES,
  sourceTypeSourceOrder,
} from '../../lib/nav-registry'
import type { SourceTypeKind } from '../../lib/nav-registry'
import type { LucideIcon } from 'lucide-react'
import { formatTimestamp } from '../../lib/date-format'
import { StagedSourcesSection } from '../StagedSourcesSection'
import { FreshnessSuggestionsSection } from '../FreshnessSuggestionsSection'
import { ActionMenu } from '../ui/ActionMenu'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { PageHeader } from '../ui/PageHeader'
import { Skeleton } from '../ui/Skeleton'
import { Toolbar } from '../ui/Toolbar'
import { cx } from '../ui/cx'

const AddSourceDialog = lazy(() => import('../AddSourceDialog'))

type SummaryStatus = SourceTypeSummary['status']
type StatusFilter = 'all' | SummaryStatus

/** 每类主操作：label 是可访问名称 + 按钮文案，run 是导航/深链。 */
interface TypeAction {
  label: string
  run: (ctx: { selectSection: (section: AppSection) => void; openAddSource: (tab: 'rss' | 'rsshub') => void }) => void
}

/** 已知类型 → 图标 + 主操作（图标优先取 nav-registry 同 sourceType
 * 入口——与侧栏同源；rsshub 无侧栏入口，用 Radio 兜底）。 */
const TYPE_ACTIONS: Partial<Record<SourceTypeKind, TypeAction>> = {
  rss: {
    label: '订阅中心',
    run: ({ selectSection }) => selectSection('subscriptions'),
  },
  rsshub: {
    // RSSHub 的管理动作 = 经既有添加来源流程订阅新路由（0014 三模式
    // 单表面）；本页直接打开 RssHubTab，不复制目录逻辑。
    label: '添加路由',
    run: ({ openAddSource }) => openAddSource('rsshub'),
  },
  api_source: {
    label: '管理',
    run: () => requestOpenSettings('api-sources'),
  },
  newsletter: {
    label: '管理连接',
    run: () => requestOpenSettings('mail'),
  },
  inbox: {
    label: '打开收件箱',
    run: ({ selectSection }) => selectSection('inbox'),
  },
  obsidian: {
    label: '打开 Obsidian',
    run: ({ selectSection }) => selectSection('obsidian'),
  },
  bookmark: {
    label: '打开书签',
    run: ({ selectSection }) => selectSection('bookmarks'),
  },
  clip: {
    label: '打开剪藏',
    run: ({ selectSection }) => selectSection('clips'),
  },
  snapshot: {
    label: '打开快照',
    run: ({ selectSection }) => selectSection('snapshots'),
  },
}

/** 集合类（内容就在 Lumi 里）ok → 正常；服务/连接类 ok → 已连接。 */
const COLLECTION_TYPES: ReadonlySet<string> = new Set(['bookmark', 'clip', 'snapshot'])

const STATUS_LABELS: Record<SummaryStatus, string> = {
  ok: '已连接',
  empty: '暂无内容',
  not_configured: '未配置',
  error: '最近错误',
}

const STATUS_FILTER_OPTIONS: Array<{ value: StatusFilter; label: string }> = [
  { value: 'all', label: '全部状态' },
  { value: 'ok', label: '已连接' },
  { value: 'empty', label: '暂无内容' },
  { value: 'not_configured', label: '未配置' },
  { value: 'error', label: '最近错误' },
]

/** 图标表：注册表同 sourceType 入口的图标（与侧栏同源）+ rsshub 兜底
 * （Radio；rsshub 无侧栏入口）。模块级查表让 JSX 里的 Icon 引用静态
 * 可追溯（react(static-components)）。 */
const TYPE_ICONS: Readonly<Record<string, LucideIcon>> = Object.fromEntries(
  NAV_ENTRIES.filter((entry) => entry.sourceType != null).map((entry) => [
    entry.sourceType as string,
    entry.icon,
  ]),
)

function statusLabelOf(item: SourceTypeSummary): string {
  if (item.status === 'ok' && COLLECTION_TYPES.has(item.type)) return '正常'
  return STATUS_LABELS[item.status]
}

function statusChipClass(status: SummaryStatus): string {
  switch (status) {
    case 'ok':
      return 'bg-[var(--lumi-success-soft)] text-[var(--lumi-success)]'
    case 'error':
      return 'bg-[var(--lumi-danger-soft)] text-[var(--lumi-danger)]'
    case 'not_configured':
      return 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent)]'
    default:
      return 'bg-[var(--lumi-surface-hover)] text-[var(--lumi-text-tertiary)]'
  }
}

function TypeRow({
  item,
  onAction,
}: {
  item: SourceTypeSummary
  onAction?: () => void
}) {
  const known = sourceTypeSourceOrder().find((meta) => meta.type === item.type)
  const label = known?.label ?? item.type
  const Icon = TYPE_ICONS[item.type] ?? Radio
  const action = TYPE_ACTIONS[item.type as SourceTypeKind]
  return (
    <li className="flex items-center gap-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2.5">
      <span
        aria-hidden
        className="flex size-9 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-hover)] text-[var(--lumi-text-secondary)]"
      >
        <Icon className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-2 text-sm text-[var(--lumi-text-primary)]">
          <span className="truncate">{label}</span>
          <span
            className={cx(
              'shrink-0 rounded-[var(--lumi-radius-sm)] px-1.5 py-0.5 text-[10px]',
              statusChipClass(item.status),
            )}
          >
            {statusLabelOf(item)}
          </span>
        </p>
        <p className="mt-0.5 text-xs text-[var(--lumi-text-tertiary)]">
          {item.count != null ? (
            <span className="tabular-nums">{item.count} 项</span>
          ) : null}
          {item.count != null && item.lastActivityAt != null ? ' · ' : null}
          {item.lastActivityAt != null
            ? `最近更新：${formatTimestamp(item.lastActivityAt)}`
            : null}
          {item.count == null && item.lastActivityAt == null ? '尚未接入' : null}
        </p>
        {item.status === 'error' && item.detail != null && (
          <p role="alert" className="mt-0.5 text-xs text-[var(--lumi-danger)]">
            {item.detail}
          </p>
        )}
      </div>
      {action && onAction && (
        <Button
          variant="secondary"
          size="sm"
          onClick={onAction}
          className="shrink-0 min-h-11 max-lg:min-h-11 lg:min-h-9 text-xs"
        >
          {action.label}
        </Button>
      )}
    </li>
  )
}

export default function SourcesPage() {
  const summary = useSourcesSummary()
  const selectSection = useReaderUi((s) => s.selectSection)
  // null = 关闭；'rss'/'rsshub' = 深链直开的添加来源模式（按需挂载，
  // initialTab 只在首次挂载时生效）。
  const [addTab, setAddTab] = useState<'rss' | 'rsshub' | null>(null)
  const openAddSource = (tab: 'rss' | 'rsshub') => setAddTab(tab)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<'all' | SourceTypeKind>('all')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')

  const order = useMemo(() => sourceTypeSourceOrder(), [])
  const allItems = summary.data?.items

  const visible = useMemo(() => {
    const needle = search.trim()
    return (allItems ?? []).filter((item) => {
      if (typeFilter !== 'all' && item.type !== typeFilter) return false
      if (statusFilter !== 'all' && item.status !== statusFilter) return false
      if (needle) {
        const label = order.find((meta) => meta.type === item.type)?.label ?? item.type
        if (!label.includes(needle) && !item.type.includes(needle)) return false
      }
      return true
    })
  }, [allItems, order, search, statusFilter, typeFilter])

  // 全部类型都处于「未配置/为空」= 还没有任何内容来源（首启空态）。
  const nothingConfigured =
    allItems != null &&
    allItems.length > 0 &&
    allItems.every((item) => item.status === 'not_configured' || item.status === 'empty')

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {addTab !== null && (
        <Suspense fallback={null}>
          <AddSourceDialog
            key={addTab}
            open
            initialTab={addTab}
            onClose={() => setAddTab(null)}
          />
        </Suspense>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto p-3 max-lg:pb-[calc(4.75rem_+_var(--safe-bottom))]">
        <PageHeader
          title="来源"
          subtitle="全部内容来源的总览；管理在各来源自己的控制面进行。"
          actions={
            <Button
              variant="secondary"
              size="sm"
              onClick={() => openAddSource('rss')}
              aria-haspopup="dialog"
              className="min-h-11 max-lg:min-h-11 lg:min-h-9 text-xs"
            >
              <Plus aria-hidden className="size-3.5" />
              添加来源
            </Button>
          }
        />

        {/* 搜索 / 类型 / 状态过滤统一一行（Toolbar + ActionMenu 原语） */}
        <Toolbar
          aria-label="来源过滤"
          className="mt-3"
          segmented={
            <>
              <div className="relative min-w-0 flex-1">
                <Search
                  aria-hidden
                  className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-[var(--lumi-text-tertiary)]"
                />
                <input
                  type="search"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="搜索来源类型"
                  aria-label="搜索来源类型"
                  className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] pl-8 pr-3 text-sm text-[var(--lumi-text-primary)] lg:min-h-9 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                />
              </div>
              <ActionMenu
                trigger={({ open, triggerProps }) => (
                  <Button
                    variant="secondary"
                    size="sm"
                    aria-expanded={open}
                    className="min-h-11 max-lg:min-h-11 lg:min-h-9 shrink-0 text-xs"
                    {...triggerProps}
                  >
                    <SlidersHorizontal aria-hidden className="size-3.5" />
                    {typeFilter === 'all'
                      ? '全部类型'
                      : (order.find((meta) => meta.type === typeFilter)?.label ?? typeFilter)}
                  </Button>
                )}
                entries={[
                  { type: 'item', label: '全部类型', onSelect: () => setTypeFilter('all') },
                  ...order.map((meta) => ({
                    type: 'item' as const,
                    label: meta.label,
                    onSelect: () => setTypeFilter(meta.type),
                  })),
                ]}
              />
              <ActionMenu
                trigger={({ open, triggerProps }) => (
                  <Button
                    variant="secondary"
                    size="sm"
                    aria-expanded={open}
                    className="min-h-11 max-lg:min-h-11 lg:min-h-9 shrink-0 text-xs"
                    {...triggerProps}
                  >
                    <SlidersHorizontal aria-hidden className="size-3.5" />
                    {STATUS_FILTER_OPTIONS.find((option) => option.value === statusFilter)?.label}
                  </Button>
                )}
                entries={STATUS_FILTER_OPTIONS.map((option) => ({
                  type: 'item' as const,
                  label: option.label,
                  onSelect: () => setStatusFilter(option.value),
                }))}
              />
            </>
          }
        />

        {summary.isPending ? (
          <div className="mt-3 flex flex-col gap-2" aria-label="来源加载中">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-14 w-full" />
            ))}
          </div>
        ) : summary.isError ? (
          <div className="mt-3 text-sm text-[var(--lumi-danger)]" role="alert">
            <p>来源汇总加载失败</p>
            <p className="mt-1 text-xs text-[var(--lumi-text-secondary)]">
              {summary.error instanceof Error ? summary.error.message : '请稍后重试。'}
            </p>
            <Button size="sm" onClick={() => summary.refetch()} className="mt-2">
              重试
            </Button>
          </div>
        ) : nothingConfigured ? (
          <EmptyState
            className="mt-6"
            icon={<Layers aria-hidden />}
            title="还没有内容来源"
            description="从订阅第一个 RSS 源开始，或接入书签、剪藏等其他来源。"
            action={
              <Button
                variant="primary"
                size="sm"
                onClick={() => openAddSource('rss')}
                aria-haspopup="dialog"
              >
                <Plus aria-hidden className="size-3.5" />
                添加来源
              </Button>
            }
          />
        ) : visible.length === 0 ? (
          <EmptyState
            className="mt-6"
            icon={<SlidersHorizontal aria-hidden />}
            title="没有匹配的来源"
            description="调整搜索词或过滤条件后再试。"
            action={
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  setSearch('')
                  setTypeFilter('all')
                  setStatusFilter('all')
                }}
              >
                清除过滤
              </Button>
            }
          />
        ) : (
          <div className="mt-3 flex flex-col gap-4">
            <ul className="flex flex-col gap-1.5">
              {visible.map((item) => {
                const action = TYPE_ACTIONS[item.type as SourceTypeKind]
                return (
                  <TypeRow
                    key={item.type}
                    item={item}
                    onAction={
                      action === undefined
                        ? undefined
                        : () => action.run({ selectSection, openAddSource })
                    }
                  />
                )
              })}
            </ul>
            {/* N016：待评估（暂存池）——空池不渲染 */}
            <StagedSourcesSection />
            {/* N014：自适应低活跃建议（建议面板 + 接受记录 + 原生界面委托） */}
            <FreshnessSuggestionsSection />
          </div>
        )}
      </div>
    </div>
  )
}
