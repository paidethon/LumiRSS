/** N050 阅读路径面板（EntryList 工具区；纯设备本地）。
 *
 * - 列表：本机打开过的条目序列（最近在尾部；会话以 30 分钟无活动
 *   窗口划分，仅呈现不强制分组）；
 * - 恢复：从最近一条开始按原顺序回放（本组件维护回放游标，用户以
 *   「下一篇」节奏推进——绝不自动导航）；
 * - 停用/清空：设备本地开关；关闭后记录即停（record no-op）。
 * 面板数据只来自 localStorage；不发起任何网络请求。
 */

import { useEffect, useMemo, useState } from 'react'
import { Map as MapIcon, RotateCcw, Trash2, X } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import {
  clearReadingPath,
  getReadingPath,
  setReadingPathEnabled,
} from '../lib/reading-path'
import type { ReadingPathEntry } from '../lib/reading-path'
import { resolveItems } from '../api/client'
import { Button } from './ui/Button'
import { EmptyState } from './ui/EmptyState'

export function ReadingPathPanel({
  onOpenEntry,
  onClose,
}: {
  onOpenEntry?: (entryRef: string) => void
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [state, setState] = useState(() => getReadingPath())
  /** 回放游标：null = 未在回放；i = 下一个要打开的 entries 下标。 */
  const [restoreIndex, setRestoreIndex] = useState<number | null>(null)
  const [resolvedTitles, setResolvedTitles] = useState<Map<string, string>>(new Map())
  const [resolveFailed, setResolveFailed] = useState(false)

  const entries = state.entries
  /** 条目标题 best-effort：先取 entry detail 缓存，缺的批量 /resolve。 */
  const [refsNeedingResolve, refsMissingDetail] = useMemo(() => {
    const cacheHits = new Map<string, string>()
    const missing: string[] = []
    for (const entry of entries) {
      if (entry.title) {
        cacheHits.set(entry.ref, entry.title)
        continue
      }
      if (!entry.ref.startsWith('rss:')) continue
      const bare = entry.ref.slice(4)
      const cached = queryClient.getQueryData<{ title?: string | null }>([
        'entry',
        bare,
        'detail',
      ])
      if (cached?.title) cacheHits.set(entry.ref, cached.title)
      else missing.push(entry.ref)
    }
    return [cacheHits, missing] as const
  }, [entries, queryClient])

  useEffect(() => {
    if (refsMissingDetail.length === 0) return
    let cancelled = false
    resolveItems(refsMissingDetail)
      .then((result) => {
        if (cancelled) return
        const next = new Map(resolvedTitles)
        for (const item of result.items) {
          if (item.title) next.set(item.ref, item.title)
        }
        setResolvedTitles(next)
      })
      .catch(() => {
        if (!cancelled) setResolveFailed(true)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refsMissingDetail.join('|')])

  function titleOf(entry: ReadingPathEntry): string {
    return (
      entry.title ??
      refsNeedingResolve.get(entry.ref) ??
      resolvedTitles.get(entry.ref) ??
      (entry.ref.startsWith('rss:') ? '条目信息不可用' : entry.ref)
    )
  }

  return (
    <section
      aria-label="阅读路径"
      data-testid="reading-path-panel"
      className="mx-4 mb-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
    >
      <div className="flex items-center gap-2">
        <MapIcon aria-hidden className="size-4 text-[var(--lumi-accent-text)]" />
        <h3 className="text-sm font-semibold text-[var(--lumi-text-primary)]">阅读路径</h3>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">仅本机记录</span>
        <span className="flex-1" />
        <IconButton label="关闭阅读路径" onClick={onClose} />
      </div>

      <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
        <Button
          size="sm"
          variant="primary"
          disabled={entries.length === 0 || restoreIndex !== null}
          onClick={() => {
            // 从最近一条开始回放（绝不自动导航：每步由用户推进）。
            const start = entries.length - 1
            setRestoreIndex(start)
            const target = entries[start]
            if (target !== undefined && onOpenEntry !== undefined) {
              onOpenEntry(target.ref.startsWith('rss:') ? target.ref.slice(4) : target.ref)
            }
          }}
        >
          <RotateCcw aria-hidden className="size-3.5" />
          恢复
        </Button>
        <label className="flex items-center gap-1 text-[var(--lumi-text-secondary)]">
          <input
            type="checkbox"
            aria-label="记录阅读路径"
            checked={state.enabled}
            onChange={(event) => {
              setReadingPathEnabled(event.target.checked)
              setState(getReadingPath())
            }}
          />
          记录我的阅读路径
        </label>
        <Button
          size="sm"
          variant="ghost"
          disabled={entries.length === 0}
          onClick={() => {
            clearReadingPath()
            setState(getReadingPath())
            setRestoreIndex(null)
          }}
        >
          <Trash2 aria-hidden className="size-3.5" />
          清空
        </Button>
      </div>

      {restoreIndex !== null && (
        <p role="status" className="mt-1 text-xs text-[var(--lumi-accent-text)]" data-testid="reading-path-restore-status">
          正在回放路径（第 {restoreIndex + 1}/{entries.length} 篇）
          {restoreIndex > 0 && (
            <Button
              size="sm"
              variant="secondary"
              className="ml-2"
              onClick={() => {
                const next = restoreIndex - 1
                setRestoreIndex(next)
                const target = entries[next]
                if (target !== undefined && onOpenEntry !== undefined) {
                  onOpenEntry(target.ref.startsWith('rss:') ? target.ref.slice(4) : target.ref)
                }
              }}
            >
              下一篇（更早）
            </Button>
          )}
        </p>
      )}

      {entries.length === 0 ? (
        <div className="mt-2">
          <EmptyState
            icon={<MapIcon aria-hidden className="size-6" />}
            title="本机还没有阅读路径"
            description="打开文章后会按顺序记录在这里（只保存在这台设备）。"
          />
        </div>
      ) : (
        <ol className="mt-2 max-h-48 space-y-0.5 overflow-y-auto rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)]">
          {entries.map((entry, index) => (
            <li
              key={`${entry.ref}-${entry.at}-${index}`}
              className="flex items-center gap-2 px-2.5 py-1 text-xs"
            >
              <span className="w-5 text-right text-[var(--lumi-text-tertiary)]">{index + 1}</span>
              <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-primary)]">
                {titleOf(entry)}
              </span>
              <span className="text-[10px] text-[var(--lumi-text-tertiary)]">
                {entry.at.slice(5, 16).replace('T', ' ')}
              </span>
            </li>
          ))}
        </ol>
      )}
      {resolveFailed && (
        <p className="mt-1 text-[10px] text-[var(--lumi-text-tertiary)]">
          部分标题解析失败，以占位显示。
        </p>
      )}
      <p className="mt-1 text-[10px] leading-4 text-[var(--lumi-text-tertiary)]">
        阅读路径只保存在这台设备（localStorage），不上传、不同步；停用后立即停止记录。
      </p>
    </section>
  )
}

function IconButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="flex size-8 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-tertiary)] hover:bg-[var(--lumi-surface-hover)]"
    >
      <X aria-hidden className="size-4" />
    </button>
  )
}

export default ReadingPathPanel
