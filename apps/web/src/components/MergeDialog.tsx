/** MergeDialog — F082 重复资料合并（整理菜单「合并」入口）。
 *
 * 选两条记录 → 字段对照 + 保留策略（标题取主/取副、批注保留/追加）→
 * 确认。合并为单事务：标签并集、工作区取主记录、批注重挂、副记录软删
 * （relation kind='merged'）——可从回收站撤销。已合并对再请求 → 409
 * merged_already（诚实报错）。
 */

import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { applyMerge, previewMerge, type MergePreview } from '../api/client'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'

const FIELD_LABELS: Record<string, string> = {
  title: '标题',
  note: '备注',
  tags: '标签',
  url: '网址',
}

export interface MergeCandidate {
  ref: string
  title: string
}

export function MergeDialog({ items, onClose }: { items: MergeCandidate[]; onClose: () => void }) {
  const [primaryRef, setPrimaryRef] = useState('')
  const [duplicateRef, setDuplicateRef] = useState('')
  const [preview, setPreview] = useState<MergePreview | null>(null)
  const [titlePolicy, setTitlePolicy] = useState<'primary' | 'duplicate'>('primary')
  const [notePolicy, setNotePolicy] = useState<'primary' | 'append'>('primary')
  const [result, setResult] = useState<{ mergedRef: string; removedRef: string; trashed: boolean } | null>(null)

  const doPreview = useMutation({
    mutationFn: () => previewMerge(primaryRef, duplicateRef),
    onSuccess: setPreview,
  })
  const doMerge = useMutation({
    mutationFn: () => applyMerge(primaryRef, duplicateRef, { title: titlePolicy, note: notePolicy }),
    onSuccess: (r) =>
      setResult({ mergedRef: r.mergedRef, removedRef: r.removedRef, trashed: r.trashed }),
  })
  const same = primaryRef !== '' && primaryRef === duplicateRef
  const pending = doPreview.isPending || doMerge.isPending

  return (
    <Dialog
      open
      onClose={onClose}
      title="合并重复资料"
      panelClassName="max-w-xl"
      footer={
        <div className="flex w-full items-center gap-2">
          {preview !== null && result === null && (
            <Button
              variant="primary"
              size="sm"
              disabled={pending || doMerge.isPending}
              onClick={() => doMerge.mutate()}
            >
              {doMerge.isPending ? '合并中…' : '确认合并'}
            </Button>
          )}
          <div className="ml-auto">
            <Button variant="ghost" size="sm" onClick={onClose}>
              {result !== null ? '关闭' : '取消'}
            </Button>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-3" data-merge-dialog="">
        {result !== null ? (
          <div role="status" className="flex flex-col gap-2 text-sm text-[var(--lumi-text-primary)]">
            <p>合并完成。副记录已放入回收站（可撤销）。</p>
            <p className="text-xs text-[var(--lumi-text-secondary)]">
              保留：{result.mergedRef}；已软删：{result.removedRef}
            </p>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-2 max-sm:grid-cols-1">
              <label className="flex flex-col gap-1 text-xs">
                <span className="text-[var(--lumi-text-secondary)]">主记录（保留）</span>
                <select
                  value={primaryRef}
                  onChange={(e) => {
                    setPrimaryRef(e.target.value)
                    setPreview(null)
                  }}
                  aria-label="选择主记录"
                  className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 text-sm text-[var(--lumi-text-primary)]"
                >
                  <option value="">请选择…</option>
                  {items.map((c) => (
                    <option key={c.ref} value={c.ref}>{c.title}</option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs">
                <span className="text-[var(--lumi-text-secondary)]">副记录（合并后软删）</span>
                <select
                  value={duplicateRef}
                  onChange={(e) => {
                    setDuplicateRef(e.target.value)
                    setPreview(null)
                  }}
                  aria-label="选择副记录"
                  className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 text-sm text-[var(--lumi-text-primary)]"
                >
                  <option value="">请选择…</option>
                  {items.map((c) => (
                    <option key={c.ref} value={c.ref}>{c.title}</option>
                  ))}
                </select>
              </label>
            </div>
            {same && (
              <p role="alert" className="text-xs text-[var(--lumi-danger)]">
                主记录与副记录不能是同一条。
              </p>
            )}
            {preview === null && (
              <div className="flex justify-center">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={pending || !primaryRef || !duplicateRef || same}
                  onClick={() => doPreview.mutate()}
                >
                  {doPreview.isPending ? '生成对照…' : '预览对照'}
                </Button>
              </div>
            )}
            {doPreview.isError && (
              <p role="alert" className="text-xs text-[var(--lumi-danger)]">
                预览失败：{doPreview.error instanceof Error ? doPreview.error.message : '请稍后重试。'}
              </p>
            )}
            {preview !== null && (
              <div className="flex flex-col gap-2" data-merge-preview="" data-testid="merge-preview">
                <p className="text-xs text-[var(--lumi-text-tertiary)]">
                  字段对照（批注 {preview.annotationCount} 条将随策略迁移；资产引用重指不丢失）：
                </p>
                <table className="w-full text-left text-xs">
                  <thead className="text-[var(--lumi-text-secondary)]">
                    <tr>
                      <th className="px-1 py-1 font-medium">字段</th>
                      <th className="px-1 py-1 font-medium">主记录</th>
                      <th className="px-1 py-1 font-medium">副记录</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.fields.map((f) => (
                      <tr key={f.field} className="border-t border-[var(--lumi-border)]">
                        <td className="px-1 py-1 text-[var(--lumi-text-primary)]">{FIELD_LABELS[f.field] ?? f.field}</td>
                        <td className="max-w-44 truncate px-1 py-1 text-[var(--lumi-text-secondary)]">{String(f.primary ?? '—')}</td>
                        <td className="max-w-44 truncate px-1 py-1 text-[var(--lumi-text-secondary)]">{String(f.duplicate ?? '—')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="flex flex-wrap items-center gap-3 text-xs">
                  <label className="flex items-center gap-1.5">
                    标题保留
                    <select
                      value={titlePolicy}
                      onChange={(e) => setTitlePolicy(e.target.value as 'primary' | 'duplicate')}
                      aria-label="标题保留策略"
                      className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5 py-1 text-[var(--lumi-text-primary)]"
                    >
                      <option value="primary">主记录</option>
                      <option value="duplicate">副记录</option>
                    </select>
                  </label>
                  <label className="flex items-center gap-1.5">
                    批注
                    <select
                      value={notePolicy}
                      onChange={(e) => setNotePolicy(e.target.value as 'primary' | 'append')}
                      aria-label="批注策略"
                      className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5 py-1 text-[var(--lumi-text-primary)]"
                    >
                      <option value="primary">仅主记录</option>
                      <option value="append">追加副记录批注</option>
                    </select>
                  </label>
                  <span className="text-[var(--lumi-text-tertiary)]">标签恒取并集；工作区归属恒取主记录。</span>
                </div>
              </div>
            )}
            {doMerge.isError && (
              <p role="alert" className="text-xs text-[var(--lumi-danger)]">
                合并失败：{doMerge.error instanceof Error ? doMerge.error.message : '请稍后重试。'}
              </p>
            )}
          </>
        )}
      </div>
    </Dialog>
  )
}
