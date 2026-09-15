/** SourceRegistrySection — 统一来源注册表（Q-P1-06）。
 *
 * GET /api/v1/sources 的首批真实消费者：每个 LumiRSS 认识的内容来源
 * 一行，显示类型、健康状态（最近错误/最近成功）与「管理」深链——
 * 注册表是只读投影（统一 API ≠ 统一数据库），真正的订阅/连接器管理
 * 留在各自的控制面（订阅中心 / RSSHub / API 来源 / 邮件 / 收件箱 /
 * Obsidian），这里只做总览与跳转，不建第二套订阅管理。
 */

import { useSources } from '../../api/queries'
import type { SourceRegistryEntry } from '../../api/types'
import { useReaderUi } from '../../store/reader-ui'
import { requestCloseSettings, requestOpenSettings } from './settings-bridge'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'

/** 类型 → 展示名 + 管理位置动作。 */
const TYPE_META: Record<
  string,
  { label: string; manage?: () => void }
> = {
  rss: {
    label: 'RSS',
    manage: () => {
      requestCloseSettings()
      useReaderUi.getState().selectSection('home')
    },
  },
  rsshub: { label: 'RSSHub', manage: () => requestOpenSettings('rsshub') },
  api_source: {
    label: 'API 来源',
    manage: () => requestOpenSettings('api-sources'),
  },
  newsletter: { label: '邮件简报', manage: () => requestOpenSettings('mail') },
  obsidian: {
    label: 'Obsidian',
    manage: () => {
      requestCloseSettings()
      useReaderUi.getState().selectSection('obsidian')
    },
  },
  inbox: {
    label: '收件箱',
    manage: () => {
      requestCloseSettings()
      useReaderUi.getState().selectSection('inbox')
    },
  },
}

function RegistryRow({ entry }: { entry: SourceRegistryEntry }) {
  const meta = TYPE_META[entry.type]
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
        <p className="flex items-center gap-2 text-sm text-[var(--lumi-text-primary)]">
          <span className="truncate">{entry.label}</span>
          <span className="shrink-0 rounded-[var(--lumi-radius-sm)] bg-[var(--lumi-accent-soft)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-accent)]">
            {meta?.label ?? entry.type}
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
        {unhealthy && (
          <p role="alert" className="mt-0.5 text-xs text-[var(--lumi-danger)]">
            最近错误：{entry.lastError}
          </p>
        )}
      </div>
      {meta?.manage && (
        <button
          type="button"
          onClick={meta.manage}
          className="shrink-0 rounded-[var(--lumi-radius-md)] px-2 py-1 text-xs text-[var(--lumi-accent)] hover:bg-[var(--lumi-surface-hover)]"
        >
          管理
        </button>
      )}
    </li>
  )
}

export function SourceRegistrySection() {
  const sources = useSources()

  if (sources.isPending) {
    return <Skeleton className="h-32 w-full" />
  }
  if (sources.isError) {
    return (
      <p role="alert" className="text-xs text-[var(--lumi-danger)]">
        来源注册表加载失败：
        {sources.error instanceof Error ? sources.error.message : '请稍后重试。'}
      </p>
    )
  }
  if (sources.data.sources.length === 0) {
    return <EmptyState title="暂无来源" description="还没有任何内容来源。" />
  }
  return (
    <ul className="flex flex-col gap-1.5" aria-label="统一来源注册表">
      {sources.data.sources.map((entry) => (
        <RegistryRow key={`${entry.type}:${entry.id}`} entry={entry} />
      ))}
    </ul>
  )
}
