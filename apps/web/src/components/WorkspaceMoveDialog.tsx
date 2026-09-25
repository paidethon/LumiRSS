/** WorkspaceMoveDialog — N108 跨工作区移动标签。
 *
 * 从工作区条目动作打开：选择目标工作区 → 预览重复影响（目标已持有
 * 该条目时如实提示「已存在，默认跳过」）→ 执行移动（同一 ItemRef，
 * 底层对象绝不复制）。keepInSource 可选双持。
 */

import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useWorkspaces } from '../api/queries'
import { listWorkspaceItems, moveWorkspaceItem } from '../api/client'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { cx } from './ui/cx'

export default function WorkspaceMoveDialog({
  workspaceId,
  itemRef,
  itemTitle,
  onClose,
  onMoved,
}: {
  workspaceId: string
  itemRef: string
  itemTitle: string
  onClose: () => void
  /** 移动成功回调（父级刷新列表）。 */
  onMoved: () => void
}) {
  const workspaces = useWorkspaces()
  const [targetId, setTargetId] = useState('')
  const [keepInSource, setKeepInSource] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const candidates = useMemo(
    () =>
      (workspaces.data?.items ?? []).filter(
        (w: { id: string }) => w.id !== workspaceId,
      ),
    [workspaces.data, workspaceId],
  )

  // 重复影响预览：目标工作区已持有该条目 → 移动将幂等跳过（不复制）。
  const targetItems = useQuery({
    queryKey: ['workspace-items-move-preview', targetId],
    queryFn: ({ signal }) => listWorkspaceItems(targetId, signal),
    enabled: targetId !== '',
  })
  const duplicateInTarget =
    targetId !== '' &&
    (targetItems.data?.items ?? []).some((item) => item.itemRef === itemRef)

  const move = useMutation({
    mutationFn: () =>
      moveWorkspaceItem(workspaceId, itemRef, {
        targetWorkspaceId: targetId,
        keepInSource,
      }),
    onSuccess: () => {
      onMoved()
      onClose()
    },
    onError: (err: unknown) => {
      const type =
        typeof err === 'object' && err !== null && 'type' in err
          ? String((err as { type: unknown }).type)
          : ''
      if (type === 'workspace_item_duplicate') {
        setError('目标工作区已存在该条目（冲突模式）。')
      } else {
        setError(err instanceof Error ? err.message : '移动失败，请稍后重试。')
      }
    },
  })

  return (
    <Dialog open onClose={onClose} title="移动到其他工作区">
      <div className="flex flex-col gap-3" data-testid="workspace-move-dialog">
        <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          将「{itemTitle}」移动到另一个工作区。移动只改变成员关系——
          条目内容不会被复制，两个工作区始终解析同一个对象。
        </p>
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-[var(--lumi-text-secondary)]">目标工作区</span>
          <select
            data-testid="workspace-move-target"
            value={targetId}
            onChange={(e) => setTargetId(e.target.value)}
            className={cx(
              'min-h-9 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)]',
              'bg-[var(--lumi-surface)] px-2 py-1.5 text-sm text-[var(--lumi-text-primary)]',
            )}
          >
            <option value="">选择目标…</option>
            {candidates.map((w: { id: string; name: string }) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </label>
        {duplicateInTarget && (
          <p
            role="status"
            data-testid="workspace-move-duplicate"
            className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1.5 text-xs text-[var(--lumi-text-secondary)]"
          >
            目标工作区已持有该条目：执行后将跳过重复添加（默认），并按下方
            「保留原工作区」开关决定源成员关系。
          </p>
        )}
        <label className="flex items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
          <input
            type="checkbox"
            checked={keepInSource}
            onChange={(e) => setKeepInSource(e.target.checked)}
          />
          保留在原工作区（两个工作区同时持有）
        </label>
        {error !== null && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            取消
          </Button>
          <Button
            variant="primary"
            size="sm"
            data-testid="workspace-move-confirm"
            disabled={targetId === '' || move.isPending}
            onClick={() => move.mutate()}
          >
            {move.isPending ? '移动中…' : '移动'}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}

