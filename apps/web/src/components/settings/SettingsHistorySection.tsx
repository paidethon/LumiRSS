/** SettingsHistorySection — F33/F111：设置变更历史、diff 展示与回退确认。
 *
 * - 每条记录展示「键: before → after」（对象值 JSON.stringify 渲染，
 *   修掉 [object Object]；秘密键值在服务端已替换为 ***）；
 * - 「撤销」先弹确认对话框（将影响的键 + 目标值），执行后展示结果：
 *   applied N / skipped 列表 + 原因（键已被后续修改 → 跳过，不静默）；
 * - 撤销成功后失效 portable 设置缓存（UI 即时反映）。 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { getSettingsHistory, revertSettingsHistory } from '../../api/client'
import { Button } from '../ui/Button'

type DiffMap = Record<string, { before?: unknown; after?: unknown }>

function fmtValue(value: unknown): string {
  if (value === undefined || value === null) return '（空）'
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch {
      return String(value)
    }
  }
  return String(value)
}

export function SettingsHistorySection() {
  const history = useQuery({
    queryKey: ['settings-history'],
    queryFn: ({ signal }) => getSettingsHistory(signal, 10),
    staleTime: 30_000,
  })
  const queryClient = useQueryClient()
  // F111：确认对话框（entryId）+ 结果展示
  // N184：冲突显式化——restored/conflicts（服务端逐键给出原因），不再静默。
  const [confirmId, setConfirmId] = useState<number | null>(null)
  const [result, setResult] = useState<{
    applied: Record<string, unknown>
    skipped: Record<string, unknown>
    restored: string[]
    conflicts: { key: string; reason: string }[]
  } | null>(null)

  const revert = useMutation({
    mutationFn: (historyId: number) => revertSettingsHistory(historyId),
    onSuccess: async (data) => {
      setResult({
        applied: data.applied,
        skipped: data.skipped,
        restored: data.restored ?? [],
        conflicts: data.conflicts ?? [],
      })
      setConfirmId(null)
      await queryClient.invalidateQueries({ queryKey: ['settings-history'] })
      await queryClient.invalidateQueries({ queryKey: ['server-settings'] })
    },
  })

  const confirmEntry =
    confirmId !== null && history.data
      ? history.data.items.find((item) => item.id === confirmId)
      : undefined

  if (history.isPending) return null
  if (history.isError) {
    return (
      <p className="text-xs text-[var(--lumi-text-tertiary)]">设置历史加载失败。</p>
    )
  }
  const items = history.data.items
  return (
    <div className="py-3" data-settings-history>
      <div className="text-sm font-medium text-[var(--lumi-text-primary)]">设置变更历史</div>
      {items.length === 0 ? (
        <p className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">
          还没有可回退的设置变更；每次修改外观/阅读等设置后会记录一条（最多 20 条）。
        </p>
      ) : (
        <ul className="mt-2 flex flex-col divide-y divide-[var(--lumi-separator)]">
          {items.map((entry) => {
            const keys = Object.keys(entry.diff)
            return (
              <li
                key={entry.id}
                className="flex min-h-11 flex-wrap items-center justify-between gap-2 py-2"
              >
                <div className="min-w-0">
                  <div className="text-xs text-[var(--lumi-text-primary)]">
                    {entry.action === 'revert' ? '回退' : '修改'} · {keys.length} 个键 ·{' '}
                    {entry.changedAt.slice(0, 16).replace('T', ' ')}
                  </div>
                  <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">
                    {keys.map((key) => {
                      const change = (entry.diff as DiffMap)[key]
                      return (
                        <span key={key} data-history-key={key}>
                          {key}: {fmtValue(change?.before)} → {fmtValue(change?.after)}
                        </span>
                      )
                    })}
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  data-revert-id={entry.id}
                  onClick={() => {
                    setResult(null)
                    setConfirmId(entry.id)
                  }}
                >
                  撤销
                </Button>
              </li>
            )
          })}
        </ul>
      )}

      {/* F111：撤销确认对话框——列将影响的键与目标值 */}
      {confirmEntry !== undefined ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="确认撤销设置变更"
          data-revert-confirm=""
          className="mt-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3"
        >
          <p className="text-xs font-medium text-[var(--lumi-text-primary)]">
            撤销这条修改？（将影响的键与目标值）
          </p>
          <ul className="mt-1 flex flex-col gap-0.5 text-[11px] text-[var(--lumi-text-secondary)]">
            {Object.keys(confirmEntry.diff).map((key) => {
              const change = (confirmEntry.diff as DiffMap)[key]
              return (
                <li key={key}>
                  {key} → {fmtValue(change?.before)}
                </li>
              )
            })}
          </ul>
          <div className="mt-2 flex gap-2">
            <Button
              variant="primary"
              size="sm"
              data-revert-confirm-run=""
              disabled={revert.isPending}
              onClick={() => revert.mutate(confirmEntry.id)}
            >
              {revert.isPending ? '撤销中…' : '确认撤销'}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setConfirmId(null)}>
              取消
            </Button>
          </div>
        </div>
      ) : null}

      {/* F111/N184：结果展示——已回退键 + 显式冲突清单（键 + 原因） */}
      {result !== null ? (
        <div
          className="mt-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3 text-xs"
          data-revert-result=""
        >
          <p className="font-medium text-[var(--lumi-text-primary)]">
            已回退 {result.restored.length} 个键。
          </p>
          {result.restored.length > 0 && (
            <p className="mt-0.5 text-[var(--lumi-text-secondary)]">
              回退生效：{result.restored.join('、')}
            </p>
          )}
          {result.conflicts.length > 0 ? (
            <div className="mt-1" data-revert-conflicts="">
              <p className="text-[var(--lumi-text-secondary)]">
                冲突 {result.conflicts.length} 个键，未回退：
              </p>
              <ul className="mt-0.5 flex flex-col gap-0.5">
                {result.conflicts.map((conflict) => (
                  <li key={conflict.key} data-revert-conflict={conflict.key} className="text-[var(--lumi-text-secondary)]">
                    {conflict.key}——{conflict.reason}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <div className="mt-2">
            <Button variant="ghost" size="sm" onClick={() => setResult(null)}>
              知道了
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  )
}
