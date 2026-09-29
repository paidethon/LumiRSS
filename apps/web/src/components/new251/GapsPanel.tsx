/** NEW-257 资料缺口任务 — 需要但尚未找到的资料 + 挂材料关闭。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { closeGap, createGap, listGaps, reopenGap } from '../../api/new251'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { ErrorLine, NoticeLine, StatusBadge, TextField } from './parts'

export function GapsPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const [description, setDescription] = useState('')
  const [materialType, setMaterialType] = useState('')
  const [closeDrafts, setCloseDrafts] = useState<Record<string, string>>({})
  const [reopenDrafts, setReopenDrafts] = useState<Record<string, string>>({})
  const [notice, setNotice] = useState<string | null>(null)

  const gaps = useQuery({
    queryKey: ['new257-gaps', projectId],
    queryFn: ({ signal }) => listGaps(projectId, signal),
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['new257-gaps', projectId] })

  const createMutation = useMutation({
    mutationFn: () => createGap(projectId, { description, materialType: materialType || undefined }),
    onSuccess: async () => {
      setDescription('')
      setMaterialType('')
      setNotice('缺口已登记。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '登记失败'),
  })
  const closeMutation = useMutation({
    mutationFn: (args: { gapId: string; itemRef: string }) => closeGap(args.gapId, { itemRef: args.itemRef }),
    onSuccess: async () => {
      setNotice('缺口已关闭（材料已挂接）。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '关闭失败'),
  })
  const reopenMutation = useMutation({
    mutationFn: (args: { gapId: string; reason: string }) => reopenGap(args.gapId, args.reason || undefined),
    onSuccess: async () => {
      setNotice('缺口已重开（曾关闭的事实保留在备注里）。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '重开失败'),
  })

  const items = gaps.data?.items ?? []
  return (
    <div data-new257-gaps="" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-48 flex-1">
          <TextField label="缺什么资料" value={description} onChange={setDescription} />
        </div>
        <div className="min-w-32 flex-1">
          <TextField label="资料类型标签（可选）" value={materialType} onChange={setMaterialType} placeholder="档案 / 报刊 / 数据" />
        </div>
        <Button size="sm" onClick={() => createMutation.mutate()} disabled={createMutation.isPending}>
          登记缺口
        </Button>
      </div>
      <NoticeLine notice={notice} />
      <ErrorLine error={gaps.error} />
      {gaps.data !== undefined && (
        <p className="text-xs text-[var(--lumi-text-tertiary)]">
          未解决 {gaps.data.openCount} · 已关闭 {gaps.data.closedCount}
        </p>
      )}
      {gaps.data !== undefined && items.length === 0 && (
        <EmptyState title="尚无资料缺口" description="列出研究需要但尚未找到的资料，找到后挂接关闭。" />
      )}
      <ul className="flex flex-col gap-2">
        {items.map((gap) => (
          <li key={gap.id} data-new257-gap={gap.id} className="flex flex-col gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="text-sm text-[var(--lumi-text-primary)]">{gap.description}</p>
                {gap.materialType !== null && (
                  <p className="text-xs text-[var(--lumi-text-tertiary)]">类型：{gap.materialType}</p>
                )}
              </div>
              <StatusBadge status={gap.status} />
            </div>
            {gap.closeNote !== null && (
              <p className="text-xs text-[var(--lumi-text-secondary)]">备注：{gap.closeNote}</p>
            )}
            {gap.status === 'open' ? (
              <div className="flex items-end gap-2">
                <div className="min-w-40 flex-1">
                  <TextField
                    label="挂上找到的材料 ItemRef"
                    value={closeDrafts[gap.id] ?? ''}
                    onChange={(value) => setCloseDrafts((prev) => ({ ...prev, [gap.id]: value }))}
                    placeholder="rss:… / library:…"
                  />
                </div>
                <Button
                  size="sm"
                  onClick={() => closeMutation.mutate({ gapId: gap.id, itemRef: closeDrafts[gap.id] ?? '' })}
                  disabled={closeMutation.isPending}
                >
                  挂材料并关闭
                </Button>
              </div>
            ) : (
              <div className="flex items-end gap-2">
                <div className="min-w-40 flex-1">
                  <TextField
                    label="重开原因（可选）"
                    value={reopenDrafts[gap.id] ?? ''}
                    onChange={(value) => setReopenDrafts((prev) => ({ ...prev, [gap.id]: value }))}
                  />
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => reopenMutation.mutate({ gapId: gap.id, reason: reopenDrafts[gap.id] ?? '' })}
                  disabled={reopenMutation.isPending}
                >
                  重开缺口
                </Button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
