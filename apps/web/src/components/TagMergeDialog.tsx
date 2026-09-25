/** TagMergeDialog — pool #16 合并标签对话框（GraphPage 使用）。
 *
 * 选源/目标 → 只读预览受影响数量 → 确认事务化合并；失败原样内联
 * 透出，不半合并。
 * N150：合并成功后进入「已合并」态——24h 窗口内可一键撤销本次合并
 * （409/404 错误诚实内联，绝不静默）。
 */

import { useState } from 'react'
import {
  useTagMergeMutation,
  useTagMergePreview,
  useTagMergeUndoMutation,
} from '../api/queries'
import type { TagSummary } from '../api/client'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'

export function TagMergeDialog({
  tagList,
  onClose,
}: {
  tagList: TagSummary[]
  onClose: () => void
}) {
  const [sourceId, setSourceId] = useState<number | null>(null)
  const [targetId, setTargetId] = useState<number | null>(null)
  const preview = useTagMergePreview(sourceId, targetId)
  const merge = useTagMergeMutation()
  const undo = useTagMergeUndoMutation()
  // N150：合并完成后的结果态（非 null = 显示撤销入口）。
  const [merged, setMerged] = useState<{ moved: number; deduped: number } | null>(null)
  const [undoError, setUndoError] = useState<string | null>(null)

  if (merged !== null) {
    return (
      <Dialog open onClose={onClose} title="合并完成">
        <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]" aria-live="polite">
          已移动 {merged.moved} 个绑定，折叠 {merged.deduped} 个重复绑定。
          合并后 24 小时内可以撤销（恢复源标签及其绑定；目标保留合并来的绑定）。
        </p>
        {undo.isError && (
          <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">
            {undoError ?? '撤销失败，请重试。'}
          </p>
        )}
        {undo.isSuccess && (
          <p role="status" className="mt-2 text-xs text-[var(--lumi-text-secondary)]">
            已撤销：源标签「{undo.data.name}」已恢复（{undo.data.restoredBindings} 个绑定）。
          </p>
        )}
        <div className="mt-4 flex justify-end gap-2">
          {!undo.isSuccess && (
            <Button
              variant="secondary"
              size="sm"
              data-testid="merge-undo"
              disabled={undo.isPending}
              onClick={() => {
                setUndoError(null)
                undo.mutate(undefined, {
                  onError: (error) => {
                    setUndoError(
                      error instanceof Error ? error.message : '撤销失败，请重试。',
                    )
                  },
                })
              }}
            >
              {undo.isPending ? '撤销中…' : '撤销本次合并'}
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={onClose}>
            {undo.isSuccess ? '关闭' : '完成'}
          </Button>
        </div>
      </Dialog>
    )
  }

  return (
    <Dialog open onClose={onClose} title="合并标签">
      <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        源标签的全部条目绑定并入目标标签（重复绑定自动折叠），源标签随后删除。
      </p>
      <div className="mt-3 flex flex-col gap-2">
        <select
          aria-label="源标签"
          value={sourceId === null ? '' : sourceId}
          onChange={(e) => setSourceId(e.target.value === '' ? null : Number(e.target.value))}
          className="min-h-9 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-sm"
        >
          <option value="">选择源标签…</option>
          {tagList.map((t) => (
            <option key={t.id ?? 0} value={t.id ?? 0}>#{t.name}</option>
          ))}
        </select>
        <select
          aria-label="目标标签"
          value={targetId === null ? '' : targetId}
          onChange={(e) => setTargetId(e.target.value === '' ? null : Number(e.target.value))}
          className="min-h-9 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-sm"
        >
          <option value="">选择目标标签…</option>
          {tagList.filter((t) => t.id !== sourceId).map((t) => (
            <option key={t.id ?? 0} value={t.id ?? 0}>#{t.name}</option>
          ))}
        </select>
        {sourceId !== null && targetId !== null && (
          <p className="text-xs text-[var(--lumi-text-secondary)]" aria-live="polite">
            {preview.isPending
              ? '统计中…'
              : preview.isError
                ? '预览失败，请重试。'
                : `将移动 ${preview.data?.willMove ?? 0} 个绑定，折叠 ${preview.data?.overlaps ?? 0} 个重复绑定。`}
          </p>
        )}
        {merge.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {merge.error instanceof Error ? merge.error.message : '合并失败，请重试。'}
          </p>
        )}
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onClose}>
          取消
        </Button>
        <Button
          size="sm"
          disabled={
            sourceId === null || targetId === null || preview.isPending || merge.isPending
          }
          onClick={() => {
            if (sourceId === null || targetId === null) return
            merge.mutate(
              { sourceId, targetId },
              {
                onSuccess: (result) => {
                  setMerged({ moved: result.movedBindings, deduped: result.dedupedBindings })
                },
              },
            )
          }}
        >
          {merge.isPending ? '合并中…' : '确认合并'}
        </Button>
      </div>
    </Dialog>
  )
}
