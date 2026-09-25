/** SourcesPage — 统一来源管理页（P04）。
 *
 * GET /api/v1/sources 的管理入口（SourceRegistrySection 在设置内的
 * 只读总览之外的第一个一级页面消费者）：注册表仍是只读投影
 * （统一 API ≠ 统一数据库），本页按类型分组总览 + 每类一行「管理」
 * 深链——真正的管理留在各自控制面，不建第二套订阅管理：
 *
 *   rss        → 订阅中心（subscriptions section）
 *   rsshub     → 添加来源对话框 RSSHub 模式（AddSourceDialog RssHubTab）
 *   api_source → 设置 · API 来源（settings-bridge 直达分类）
 *   newsletter → 设置 · 邮件（settings-bridge 直达分类）
 *   inbox      → 收件箱 section
 *   obsidian   → Obsidian 库 section
 *
 * 行内健康面只渲染 API 真实提供的字段（enabled / lastSuccessAt /
 * lastError），不发明状态；注册表出现未知类型时按原样渲染（无深链），
 * 不假设类型集合封闭。
 *
 * 底栏「来源」tab 与桌面侧栏「来源」都导航到本页（AppSection sources）；
 * 旧「订阅」入口保留（本页 RSS 组深链 + 侧栏 RSS 订阅行）。
 */

import { Suspense, lazy, useState } from 'react'
import { Layers, Plus } from 'lucide-react'
import { useSources } from '../../api/queries'
import type { SourceRegistryEntry } from '../../api/types'
import { useReaderUi } from '../../store/reader-ui'
import type { AppSection } from '../../store/reader-ui'
import { requestOpenSettings } from '../settings/settings-bridge'
import { formatTimestamp } from '../../lib/date-format'
import { StagedSourcesSection } from '../StagedSourcesSection'
import { FreshnessSuggestionsSection } from '../FreshnessSuggestionsSection'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'

const AddSourceDialog = lazy(() => import('../AddSourceDialog'))

/** 深链上下文：section 导航 + 打开添加来源（RSSHub 深链用）。 */
interface ManageContext {
  selectSection: (section: AppSection) => void
  openAddSource: (tab: 'rss' | 'rsshub') => void
}

/** 已知类型 → 分组名 + 管理位置动作（顺序即分组展示顺序）。 */
const TYPE_ORDER: ReadonlyArray<{
  type: string
  label: string
  manage?: (ctx: ManageContext) => void
}> = [
  {
    type: 'rss',
    label: 'RSS 订阅',
    manage: ({ selectSection }) => selectSection('subscriptions'),
  },
  {
    type: 'rsshub',
    label: 'RSSHub 路由',
    // RSSHub 的管理动作 = 经既有添加来源流程订阅新路由（0014 三模式
    // 单表面）；本页直接打开 RssHubTab，不复制目录逻辑。
    manage: ({ openAddSource }) => openAddSource('rsshub'),
  },
  {
    type: 'api_source',
    label: 'API 来源',
    manage: () => requestOpenSettings('api-sources'),
  },
  {
    type: 'newsletter',
    label: '邮件桥',
    manage: () => requestOpenSettings('mail'),
  },
  {
    type: 'inbox',
    label: '收件箱',
    manage: ({ selectSection }) => selectSection('inbox'),
  },
  {
    type: 'obsidian',
    label: 'Obsidian',
    manage: ({ selectSection }) => selectSection('obsidian'),
  },
]

/** 按注册表实际返回的类型分组：已知类型按 TYPE_ORDER 排前，未知类型
 * （未来新增）按原 type 追加在后——渲染不假设类型集合封闭。 */
function groupEntries(sources: SourceRegistryEntry[]): Array<{
  type: string
  label: string
  manage?: (ctx: ManageContext) => void
  entries: SourceRegistryEntry[]
}> {
  const byType = new Map<string, SourceRegistryEntry[]>()
  for (const entry of sources) {
    const bucket = byType.get(entry.type)
    if (bucket) bucket.push(entry)
    else byType.set(entry.type, [entry])
  }
  const groups: Array<{
    type: string
    label: string
    manage?: (ctx: ManageContext) => void
    entries: SourceRegistryEntry[]
  }> = []
  for (const meta of TYPE_ORDER) {
    const entries = byType.get(meta.type)
    if (entries === undefined) continue
    byType.delete(meta.type)
    groups.push({ type: meta.type, label: meta.label, manage: meta.manage, entries })
  }
  for (const [type, entries] of byType) {
    groups.push({ type, label: type, entries })
  }
  return groups
}

function RegistryRow({
  entry,
  manageLabel,
  onManage,
}: {
  entry: SourceRegistryEntry
  manageLabel: string
  onManage?: () => void
}) {
  const unhealthy = entry.lastError != null
  return (
    <li className="flex items-start gap-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2.5">
      <span
        aria-hidden
        className={cx(
          'mt-1.5 size-1.5 shrink-0 rounded-full',
          !entry.enabled || unhealthy
            ? 'bg-[var(--lumi-danger)]'
            : 'bg-[var(--lumi-success)]',
        )}
      />
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-2 text-sm text-[var(--lumi-text-primary)]">
          <span className="truncate">{entry.label}</span>
          <span className="shrink-0 rounded-[var(--lumi-radius-sm)] bg-[var(--lumi-accent-soft)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-accent)]">
            {manageLabel}
          </span>
          {!entry.enabled && (
            <span className="text-xs text-[var(--lumi-text-tertiary)]">已停用</span>
          )}
        </p>
        {entry.summary != null && (
          <p className="mt-0.5 text-xs text-[var(--lumi-text-tertiary)]">
            {entry.summary}
          </p>
        )}
        {entry.lastSuccessAt != null && (
          <p className="mt-0.5 text-xs text-[var(--lumi-text-tertiary)]">
            最近成功：{formatTimestamp(entry.lastSuccessAt)}
          </p>
        )}
        {unhealthy && (
          <p role="alert" className="mt-0.5 text-xs text-[var(--lumi-danger)]">
            最近错误：{entry.lastError}
          </p>
        )}
      </div>
      {onManage && (
        <button
          type="button"
          onClick={onManage}
          className="shrink-0 self-center rounded-[var(--lumi-radius-md)] px-3 text-xs text-[var(--lumi-accent)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] min-h-11 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        >
          管理
        </button>
      )}
    </li>
  )
}

export default function SourcesPage() {
  const sources = useSources()
  const selectSection = useReaderUi((s) => s.selectSection)
  // null = 关闭；'rss'/'rsshub' = 深链直开的添加来源模式（按需挂载，
  // initialTab 只在首次挂载时生效）。
  const [addTab, setAddTab] = useState<'rss' | 'rsshub' | null>(null)
  const openAddSource = (tab: 'rss' | 'rsshub') => setAddTab(tab)

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
      <div className="min-h-0 flex-1 overflow-y-auto p-3 max-lg:pb-[76px]">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="flex items-center gap-1.5 text-base font-semibold text-[var(--lumi-text-primary)]">
            <Layers aria-hidden className="size-4" />
            来源
          </h1>
          <div className="ml-auto flex items-center gap-1.5">
            <Button
              variant="secondary"
              onClick={() => openAddSource('rss')}
              aria-haspopup="dialog"
              className="text-xs"
            >
              <Plus aria-hidden className="size-3.5" />
              添加来源
            </Button>
          </div>
        </div>

        <p className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">
          全部内容来源的总览（只读投影）；管理在各来源自己的控制面进行。
        </p>

        {sources.isPending ? (
          <div className="mt-3 flex flex-col gap-3" aria-label="来源加载中">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : sources.isError ? (
          <div className="mt-3 text-sm text-[var(--lumi-danger)]" role="alert">
            <p>来源列表加载失败</p>
            <p className="mt-1 text-xs text-[var(--lumi-text-secondary)]">
              {sources.error instanceof Error ? sources.error.message : '请稍后重试。'}
            </p>
            <Button size="sm" onClick={() => sources.refetch()} className="mt-2">
              重试
            </Button>
          </div>
        ) : sources.data.sources.length === 0 ? (
          <EmptyState
            className="mt-6"
            icon={<Layers aria-hidden />}
            title="暂无来源"
            description="还没有任何内容来源；可以从添加来源开始。"
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
        ) : (
          <div className="mt-3 flex flex-col gap-4">
            {groupEntries(sources.data.sources).map((group) => {
              const meta = { selectSection, openAddSource }
              return (
                <section
                  key={group.type}
                  aria-label={group.label}
                  className="flex flex-col gap-1.5"
                >
                  <h2 className="px-0.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--lumi-text-tertiary)]">
                    {group.label}
                  </h2>
                  <ul className="flex flex-col gap-1.5">
                    {group.entries.map((entry) => (
                      <RegistryRow
                        key={entry.id}
                        entry={entry}
                        manageLabel={group.label}
                        onManage={
                          group.manage === undefined
                            ? undefined
                            : () => group.manage?.(meta)
                        }
                      />
                    ))}
                  </ul>
                </section>
              )
            })}
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
