/** BatchEditDialog — F081 批量元数据编辑（Bookmarks/Clips 多选入口）。
 *
 * 仅 Lumi 自有字段：标题后缀（只追加，幂等）/ 标签 add+remove（幂等）/
 * 移动工作区（记录原值）。流程：字段勾选 + 值 → 预览（零写入，逐项
 * before/after）→ 应用 → 逐项结果（仅失败可重试）。FreshRSS 条目与
 * Vault 文件永不触碰。
 */

import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  applyBatchEdit,
  previewBatchEdit,
  type BatchEditApplyItem,
  type BatchEditPatch,
  type BatchEditPreviewItem,
} from '../api/client'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { cx } from './ui/cx'

const inputCls = cx(
  'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
  'px-3 py-2 text-sm text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)]',
  'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
)

type Phase = 'edit' | 'preview' | 'result'

export function BatchEditDialog({
  refs,
  onClose,
}: {
  refs: string[]
  onClose: () => void
}) {
  const [phase, setPhase] = useState<Phase>('edit')
  const [editTitle, setEditTitle] = useState(false)
  const [titleSuffix, setTitleSuffix] = useState('')
  const [editTagsAdd, setEditTagsAdd] = useState(false)
  const [tagsAdd, setTagsAdd] = useState('')
  const [editTagsRemove, setEditTagsRemove] = useState(false)
  const [tagsRemove, setTagsRemove] = useState('')
  const [editWorkspace, setEditWorkspace] = useState(false)
  const [workspaceId, setWorkspaceId] = useState('')
  const [previewItems, setPreviewItems] = useState<BatchEditPreviewItem[]>([])
  const [results, setResults] = useState<BatchEditApplyItem[] | null>(null)
  const queryClient = useQueryClient()
  /** 仅失败重试：记住本轮应用的范围。 */
  const lastScope = useRef<string[]>(refs)

  /** 未勾选字段不出现在 patch（undefined = 保持原值）。 */
  function patch(): BatchEditPatch {
    const p: BatchEditPatch = {}
    if (editTitle && titleSuffix.trim() !== '') p.titleSuffix = titleSuffix.trim()
    if (editTagsAdd) {
      const list = tagsAdd.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
      if (list.length > 0) p.tagsAdd = list
    }
    if (editTagsRemove) {
      const list = tagsRemove.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
      if (list.length > 0) p.tagsRemove = list
    }
    if (editWorkspace && workspaceId.trim() !== '') p.workspaceId = workspaceId.trim()
    return p
  }

  const preview = useMutation({
    mutationFn: () => previewBatchEdit(refs, patch()),
    onSuccess: (data) => {
      setPreviewItems(data.items)
      setPhase('preview')
    },
  })
  const apply = useMutation({
    mutationFn: (onlyRefs: string[]) => applyBatchEdit(onlyRefs, patch()),
    onSuccess: async (data, onlyRefs) => {
      setResults(data.items)
      if (data.failed === 0) {
        await queryClient.invalidateQueries({ queryKey: ['bookmarks'] })
        await queryClient.invalidateQueries({ queryKey: ['clips'] })
      }
      // 仅失败重试：记住本轮范围。
      lastScope.current = onlyRefs
      setPhase('result')
    },
  })

  const pending = preview.isPending || apply.isPending
  const failedItems = results?.filter((r) => !r.ok) ?? []

  return (
    <Dialog
      open
      onClose={onClose}
      title={`批量编辑（已选 ${refs.length} 条）`}
      panelClassName="max-w-2xl"
      footer={
        <div className="flex items-center gap-2">
          {phase === 'result' && failedItems.length > 0 && (
            <Button
              variant="secondary"
              size="sm"
              disabled={pending}
              onClick={() =>
                apply.mutate(failedItems.map((r) => r.ref))
              }
            >
              仅重试失败（{failedItems.length}）
            </Button>
          )}
          <div className="ml-auto flex items-center gap-2">
            {phase !== 'edit' && (
              <Button variant="ghost" size="sm" disabled={pending} onClick={() => setPhase('edit')}>
                返回编辑
              </Button>
            )}
            {phase === 'edit' && (
              <Button
                variant="primary"
                size="sm"
                disabled={pending || (!editTitle && !editTagsAdd && !editTagsRemove && !editWorkspace)}
                onClick={() => preview.mutate()}
              >
                {preview.isPending ? '生成预览…' : '预览'}
              </Button>
            )}
            {phase === 'preview' && (
              <Button variant="primary" size="sm" disabled={pending} onClick={() => apply.mutate(refs)}>
                {apply.isPending ? '应用中…' : `应用到 ${refs.length} 条`}
              </Button>
            )}
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-3" data-batch-edit="">
        {phase === 'edit' && (
          <>
            <p className="text-xs text-[var(--lumi-text-secondary)]">
              仅修改 Lumi 自有元数据（标题后缀 / 标签 / 工作区归属）；未勾选的字段保持原值。
              FreshRSS 条目与 Obsidian Vault 不会改动。
            </p>
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" checked={editTitle} onChange={(e) => setEditTitle(e.target.checked)} className="mt-1" aria-label="勾选：标题追加后缀" />
              <span className="flex-1">
                <span className="text-[var(--lumi-text-primary)]">标题追加后缀</span>
                {editTitle && (
                  <input
                    type="text"
                    value={titleSuffix}
                    onChange={(e) => setTitleSuffix(e.target.value)}
                    placeholder="（已含该后缀的条目自动跳过，不重复追加）"
                    aria-label="标题后缀"
                    className={cx(inputCls, 'mt-1')}
                  />
                )}
              </span>
            </label>
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" checked={editTagsAdd} onChange={(e) => setEditTagsAdd(e.target.checked)} className="mt-1" aria-label="勾选：添加标签" />
              <span className="flex-1">
                <span className="text-[var(--lumi-text-primary)]">添加标签（逗号分隔，幂等）</span>
                {editTagsAdd && (
                  <input type="text" value={tagsAdd} onChange={(e) => setTagsAdd(e.target.value)} placeholder="tag-a, tag-b" aria-label="要添加的标签" className={cx(inputCls, 'mt-1')} />
                )}
              </span>
            </label>
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" checked={editTagsRemove} onChange={(e) => setEditTagsRemove(e.target.checked)} className="mt-1" aria-label="勾选：移除标签" />
              <span className="flex-1">
                <span className="text-[var(--lumi-text-primary)]">移除标签（逗号分隔，幂等）</span>
                {editTagsRemove && (
                  <input type="text" value={tagsRemove} onChange={(e) => setTagsRemove(e.target.value)} placeholder="tag-c" aria-label="要移除的标签" className={cx(inputCls, 'mt-1')} />
                )}
              </span>
            </label>
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" checked={editWorkspace} onChange={(e) => setEditWorkspace(e.target.checked)} className="mt-1" aria-label="勾选：移动到工作区" />
              <span className="flex-1">
                <span className="text-[var(--lumi-text-primary)]">移动到工作区（记录原工作区）</span>
                {editWorkspace && (
                  <input type="text" value={workspaceId} onChange={(e) => setWorkspaceId(e.target.value)} placeholder="工作区 ID" aria-label="目标工作区 ID" className={cx(inputCls, 'mt-1')} />
                )}
              </span>
            </label>
            {preview.isError && (
              <p role="alert" className="text-xs text-[var(--lumi-danger)]">
                预览失败：{preview.error instanceof Error ? preview.error.message : '请稍后重试。'}
              </p>
            )}
          </>
        )}

        {phase === 'preview' && (
          <div className="flex flex-col gap-2">
            <p className="text-xs text-[var(--lumi-text-tertiary)]">预览（未写入任何数据）：</p>
            <div className="max-h-64 overflow-y-auto rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)]" data-batch-preview="">
              <table className="w-full text-left text-xs">
                <thead className="bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-secondary)]">
                  <tr>
                    <th className="px-2 py-1.5 font-medium">条目</th>
                    <th className="px-2 py-1.5 font-medium">变更前</th>
                    <th className="px-2 py-1.5 font-medium">变更后</th>
                  </tr>
                </thead>
                <tbody>
                  {previewItems.map((item) => (
                    <tr key={item.ref} className="border-t border-[var(--lumi-border)]">
                      <td className="max-w-40 truncate px-2 py-1.5 text-[var(--lumi-text-primary)]">{item.before.title}</td>
                      <td className="px-2 py-1.5 text-[var(--lumi-text-tertiary)]">
                        {item.before.tags.join('、') || '—'}{item.before.workspaceIds.length > 0 ? ` @${item.before.workspaceIds.join(',')}` : ''}
                      </td>
                      <td className="px-2 py-1.5 text-[var(--lumi-text-secondary)]">
                        {item.after.tags.join('、') || '—'}{item.after.workspaceIds.length > 0 ? ` @${item.after.workspaceIds.join(',')}` : ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {phase === 'result' && results !== null && (
          <div className="flex flex-col gap-2" data-batch-result="">
            <p role="status" className="text-sm text-[var(--lumi-text-primary)]">
              应用完成：成功 {results.filter((r) => r.ok).length} 条
              {failedItems.length > 0 ? `，失败 ${failedItems.length} 条` : ''}。
            </p>
            {failedItems.length > 0 && (
              <ul className="flex flex-col gap-1 text-xs text-[var(--lumi-danger)]">
                {failedItems.map((r) => (
                  <li key={r.ref}>{r.ref}：{r.error ?? '未知错误'}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        {apply.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            应用失败：{apply.error instanceof Error ? apply.error.message : '请稍后重试。'}
          </p>
        )}
      </div>
    </Dialog>
  )
}
