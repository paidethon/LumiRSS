/** N036 来源刷新状态面板（订阅页工具区，VolumeOverview 之下）。
 *
 * - 来源状态 dots：每来源最近一次检查的 ok / stale / error（绿 / 琥珀 /
 *  红，色盲可辨的形状差异由文字标签承载）；pending = 最近一次非 ok 或
 *  存在未消费恢复窗口（N037）；
 * - 最近刷新 list：每来源最近 5 条检查记录（checkedAt / result /
 *  entryCount）；
 * - 立即检查：复用既有 F050 探测（POST /subscriptions/health-check，
 *  服务端顺带写刷新日志）——**没有任何新调度器、没有新检查端点**。
 */

import { useMemo, useState } from 'react'
import { Activity, ChevronDown, ChevronRight, Loader2, Radar } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import {
  useRefreshNowMutation,
  useSourceRefreshStatus,
  useSubscriptions,
} from '../api/queries'
import type { SourceRefreshStatusFeed } from '../api/types'
import { Button } from './ui/Button'
import { EmptyState } from './ui/EmptyState'
import { cx } from './ui/cx'

const RESULT_LABEL: Record<string, string> = {
  ok: '正常',
  stale: '断更',
  error: '错误',
}

/** 最近检查结果的呈现点：颜色 + 文字双通道（不依赖颜色单独传达）。 */
function ResultDot({ result }: { result: string }) {
  const tone =
    result === 'ok'
      ? 'bg-[var(--lumi-success)]'
      : result === 'stale'
        ? 'bg-[var(--lumi-warning)]'
        : 'bg-[var(--lumi-danger)]'
  return (
    <span className="inline-flex items-center gap-1">
      <span
        aria-hidden
        className={cx('inline-block size-2 rounded-full', tone)}
        data-testid={`refresh-dot-${result}`}
      />
      <span className="sr-only">{RESULT_LABEL[result] ?? result}</span>
    </span>
  )
}

function FeedRow({ feed }: { feed: SourceRefreshStatusFeed }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <li className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1.5">
      <div className="flex items-center gap-2">
        <ResultDot result={feed.lastResult} />
        <span className="min-w-0 flex-1 truncate text-xs text-[var(--lumi-text-primary)]">
          {feed.feedUrl}
        </span>
        {feed.recoveryAvailable && (
          <span className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-accent-soft)] px-1.5 text-[10px] text-[var(--lumi-accent-text)]">
            可补读
          </span>
        )}
        <span className="text-[10px] text-[var(--lumi-text-tertiary)]">
          {RESULT_LABEL[feed.lastResult] ?? feed.lastResult} · {feed.lastChecked.slice(0, 16).replace('T', ' ')}
        </span>
        <button
          type="button"
          aria-expanded={expanded}
          aria-label={`${expanded ? '收起' : '展开'}「${feed.feedUrl}」的最近刷新`}
          onClick={() => setExpanded((v) => !v)}
          className="flex min-h-7 items-center rounded px-1 text-[var(--lumi-text-tertiary)] hover:bg-[var(--lumi-surface-hover)]"
        >
          {expanded ? <ChevronDown aria-hidden className="size-3.5" /> : <ChevronRight aria-hidden className="size-3.5" />}
        </button>
      </div>
      {expanded && (
        <ul className="mt-1 space-y-0.5 border-t border-[var(--lumi-separator)] pt-1" data-testid="refresh-recent-list">
          {feed.recent.map((entry, index) => (
            <li key={`${entry.checkedAt}-${index}`} className="flex items-center gap-2 text-[10px] text-[var(--lumi-text-secondary)]">
              <ResultDot result={entry.result} />
              <span className="flex-1">{entry.checkedAt.replace('T', ' ')}</span>
              <span>{RESULT_LABEL[entry.result] ?? entry.result}</span>
              {entry.entryCount > 0 && <span>＋{entry.entryCount} 条</span>}
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

export function SourceRefreshStatusPanel() {
  const statusQuery = useSourceRefreshStatus()
  const subscriptionsQuery = useSubscriptions()
  const refreshNow = useRefreshNowMutation()
  const queryClient = useQueryClient()
  const [collapsed, setCollapsed] = useState(false)

  const refs = useMemo(
    () => (subscriptionsQuery.data ?? []).map((sub) => sub.subscriptionRef),
    [subscriptionsQuery.data],
  )
  const feeds = statusQuery.data?.feeds ?? []
  const pendingCount = feeds.filter((feed) => feed.pending).length

  async function runCheck() {
    if (refs.length === 0) return
    await refreshNow.mutateAsync(refs)
    await queryClient.invalidateQueries({ queryKey: ['sources', 'recoveries'] })
  }

  return (
    <section
      aria-label="来源刷新状态"
      data-testid="source-refresh-status-panel"
      className="mb-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
    >
      <div className="flex items-center gap-2">
        <button
          type="button"
          aria-expanded={!collapsed}
          onClick={() => setCollapsed((v) => !v)}
          className="flex min-h-7 items-center gap-1.5 rounded px-1 text-sm font-semibold text-[var(--lumi-text-primary)] hover:bg-[var(--lumi-surface-hover)]"
        >
          {collapsed ? <ChevronRight aria-hidden className="size-4" /> : <ChevronDown aria-hidden className="size-4" />}
          <Activity aria-hidden className="size-4 text-[var(--lumi-accent-text)]" />
          来源刷新状态
        </button>
        {pendingCount > 0 && (
          <span className="text-xs text-[var(--lumi-warning)]">{pendingCount} 个来源待关注</span>
        )}
        <span className="flex-1" />
        <Button
          size="sm"
          variant="secondary"
          onClick={runCheck}
          disabled={refreshNow.isPending || refs.length === 0}
        >
          {refreshNow.isPending ? (
            <Loader2 aria-hidden className="size-3.5 animate-spin" />
          ) : (
            <Radar aria-hidden className="size-3.5" />
          )}
          立即检查
        </Button>
      </div>
      {!collapsed && (
        <>
          <p className="mt-1 text-[10px] leading-4 text-[var(--lumi-text-tertiary)]">
            「立即检查」复用维护检查探测（手动触发，无后台调度）；同步有新交付的来源也会记录。
          </p>
          {statusQuery.isPending ? (
            <p className="mt-2 flex items-center gap-1.5 text-xs text-[var(--lumi-text-tertiary)]">
              <Loader2 aria-hidden className="size-3.5 animate-spin" /> 加载中…
            </p>
          ) : statusQuery.isError ? (
            <EmptyState icon={<Activity aria-hidden className="size-6" />} title="刷新状态加载失败" description="请稍后重试。" />
          ) : feeds.length === 0 ? (
            <EmptyState
              icon={<Radar aria-hidden className="size-6" />}
              title="还没有检查记录"
              description="点「立即检查」查看各来源状态。"
            />
          ) : (
            <ul className="mt-2 space-y-1">
              {feeds.map((feed) => (
                <FeedRow key={feed.feedUrl} feed={feed} />
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  )
}

export default SourceRefreshStatusPanel
