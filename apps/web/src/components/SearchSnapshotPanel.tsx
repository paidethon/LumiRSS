/** SearchSnapshotPanel — N141 搜索快照比较（SearchPage 面板）。
 *
 * - 列出已冻结快照（查询 + 引用计数 + 时间；引用清单绝不出站）；
 * - 「比较」对快照存储的作用域原样复跑：added / removed /
 *   rankChanges（|位移|>5）/ permissionLost 差分；complete=false 时
 *   诚实标注「结果超界，比较不完整」；
 * - 全部状态：加载 / 错误 / 空（诚实提示「还没有快照」）。
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Camera, GitCompare, Loader2 } from 'lucide-react'
import type {
  SearchSnapshotCompareResult,
  SearchSnapshotView,
} from '../api/types'
import {
  compareSearchSnapshot,
  fetchSearchSnapshots,
} from '../lib/search-insight'
import { dateTimeFormatter } from '../lib/date-format'
import { Button } from './ui/Button'

const DIFF_LIST_LIMIT = 8

function formatTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return dateTimeFormatter.format(date)
}

function DiffList({ title, refs }: { title: string; refs: string[] }) {
  if (refs.length === 0) return null
  return (
    <div data-testid={`snapshot-diff-${title}`}>
      <p className="text-[11px] font-medium text-[var(--lumi-text-secondary)]">{title}</p>
      <ul className="mt-0.5 flex flex-col gap-0.5">
        {refs.slice(0, DIFF_LIST_LIMIT).map((ref) => (
          <li key={ref} className="truncate font-mono text-[11px] text-[var(--lumi-text-tertiary)]">
            {ref}
          </li>
        ))}
      </ul>
      {refs.length > DIFF_LIST_LIMIT && (
        <p className="text-[10px] text-[var(--lumi-text-tertiary)]">
          仅显示前 {DIFF_LIST_LIMIT} 条（共 {refs.length} 条）。
        </p>
      )}
    </div>
  )
}

function CompareView({ result }: { result: SearchSnapshotCompareResult }) {
  return (
    <div
      data-testid="snapshot-compare"
      className="mt-2 flex flex-col gap-2 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface)] p-2.5"
    >
      <p className="text-xs text-[var(--lumi-text-secondary)]">
        快照 {result.counts.snapshot} 条 → 当前 {result.counts.current} 条：
        <span className="text-[var(--lumi-accent-text)]">新增 {result.counts.added}</span>
        {' · '}
        <span>移除 {result.counts.removed}</span>
        {' · '}
        <span>排名变动 {result.counts.rankChanges}</span>
        {' · '}
        <span>不可再访问 {result.counts.permissionLost}</span>
      </p>
      {!result.complete && (
        <p role="note" className="text-[11px] text-[var(--lumi-text-tertiary)]">
          快照或当前结果超过 2000 条上界，比较基于有界清单，不完整。
        </p>
      )}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <DiffList title="新增" refs={result.added} />
        <DiffList title="移除" refs={result.removed} />
        <DiffList
          title="排名变动"
          refs={result.rankChanges.map(
            (c) => `${c.entryRef}（${c.oldRank} → ${c.newRank}）`,
          )}
        />
        <DiffList title="不可再访问" refs={result.permissionLost} />
      </div>
    </div>
  )
}

function SnapshotRow({ snapshot }: { snapshot: SearchSnapshotView }) {
  const [compare, setCompare] = useState<SearchSnapshotCompareResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const runCompare = async () => {
    setPending(true)
    setError(null)
    try {
      setCompare(await compareSearchSnapshot(snapshot.id))
    } catch (e) {
      setError(e instanceof Error ? e.message : '比较失败，请稍后重试。')
    } finally {
      setPending(false)
    }
  }

  return (
    <li
      data-testid="snapshot-row"
      className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-2"
    >
      <div className="flex min-w-0 items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-xs font-medium text-[var(--lumi-text-primary)]">
          {snapshot.query}
        </span>
        <span className="shrink-0 text-[11px] tabular-nums text-[var(--lumi-text-tertiary)]">
          {snapshot.refCount} 条 · {formatTime(snapshot.createdAt)}
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void runCompare()}
          disabled={pending}
          aria-label={`比较快照「${snapshot.query}」`}
        >
          {pending ? (
            <Loader2 aria-hidden className="size-3 animate-spin" />
          ) : (
            <GitCompare aria-hidden className="size-3" />
          )}
          比较
        </Button>
      </div>
      {(snapshot.truncated || snapshot.refCount >= 2000) && (
        <p className="mt-0.5 text-[10px] text-[var(--lumi-text-tertiary)]">
          快照冻结时超过 2000 条上界，仅保存了有界清单。
        </p>
      )}
      {error !== null && (
        <p role="alert" className="mt-1 text-[11px] text-[var(--lumi-danger)]">
          {error}
        </p>
      )}
      {compare !== null && <CompareView result={compare} />}
    </li>
  )
}

export function SearchSnapshotPanel() {
  const snapshots = useQuery({
    queryKey: ['search', 'snapshots'],
    queryFn: ({ signal }) => fetchSearchSnapshots(signal),
  })
  const items = snapshots.data?.items ?? []

  return (
    <div
      data-testid="snapshot-panel"
      className="mt-2 flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
      aria-label="搜索快照"
    >
      <p className="flex items-center gap-1.5 text-xs font-medium text-[var(--lumi-text-secondary)]">
        <Camera aria-hidden className="size-3.5" />
        搜索快照
        <span className="font-normal text-[var(--lumi-text-tertiary)]">
          （最多 20 份，超出自动淘汰最老）
        </span>
      </p>

      {snapshots.isPending && (
        <p role="status" className="text-xs text-[var(--lumi-text-tertiary)]">加载中…</p>
      )}
      {snapshots.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          快照列表加载失败：{snapshots.error instanceof Error ? snapshots.error.message : '请稍后重试。'}
        </p>
      )}
      {!snapshots.isPending && !snapshots.isError && items.length === 0 && (
        <p role="status" className="text-xs text-[var(--lumi-text-tertiary)]">
          还没有快照。点上方「保存快照」冻结当前结果，稍后回来比较变化。
        </p>
      )}
      {items.length > 0 && (
        <ul className="flex flex-col gap-1.5">
          {items.map((snapshot) => (
            <SnapshotRow key={snapshot.id} snapshot={snapshot} />
          ))}
        </ul>
      )}
    </div>
  )
}
