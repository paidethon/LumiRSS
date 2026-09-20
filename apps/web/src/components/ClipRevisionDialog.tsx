/** ClipRevisionDialog — F089 剪藏手工修订（ClipsPage 阅读视图入口）。
 *
 * 块勾选（基于原始 content_html 切分的块 id 清单）+ 修订说明 → PATCH
 * revision（全移除需显式 force；原始 content_html 永不覆盖）。已修订
 * 显示「已修订」徽标 + 「查看原始版本」切换 + 恢复原始（丢弃修订）。
 * 并发修订：baseContentHash 不匹配 → 409 诚实报错。
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCheck, History } from 'lucide-react'
import { discardClipRevision, getClipBlocks, saveClipRevision } from '../api/client'
import { sanitizeArticleHtml } from '../lib/sanitize-article-html'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { Skeleton } from './ui/Skeleton'
import { cx } from './ui/cx'

function clipUuid(clipRef: string): string {
  return clipRef.startsWith('library:') ? clipRef.slice('library:'.length) : clipRef
}

export function ClipRevisionDialog({ clipRef, onClose }: { clipRef: string; onClose: () => void }) {
  const uuid = clipUuid(clipRef)
  const blocks = useQuery({
    queryKey: ['clip-blocks', uuid],
    queryFn: ({ signal }) => getClipBlocks(uuid, signal),
  })
  const [keep, setKeep] = useState<Set<string> | null>(null)
  const [note, setNote] = useState('')
  const queryClient = useQueryClient()

  const selected = keep ?? new Set((blocks.data?.blocks ?? []).map((b) => b.id))
  function toggle(id: string) {
    setKeep((prev) => {
      const base = prev ?? new Set((blocks.data?.blocks ?? []).map((b) => b.id))
      const next = new Set(base)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const save = useMutation({
    mutationFn: (force: boolean) =>
      saveClipRevision(uuid, {
        blocks: [...selected],
        note: note.trim() === '' ? null : note.trim(),
        force,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['library', 'clips'] })
      onClose()
    },
  })

  const allBlocks = blocks.data?.blocks ?? []
  const noneSelected = selected.size === 0

  return (
    <Dialog
      open
      onClose={onClose}
      title="修订正文"
      panelClassName="max-w-xl"
      footer={
        <div className="flex w-full items-center gap-2">
          <span className="text-xs text-[var(--lumi-text-tertiary)]">
            保留 {selected.size}/{allBlocks.length} 块 · 原始版本永不覆盖
          </span>
          <div className="ml-auto flex gap-2">
            <Button variant="ghost" size="sm" onClick={onClose}>取消</Button>
            <Button
              variant="primary"
              size="sm"
              disabled={save.isPending}
              onClick={() => save.mutate(noneSelected)}
            >
              {save.isPending ? '保存中…' : noneSelected ? '清空全部（显式）' : '保存修订'}
            </Button>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-3" data-clip-revision="">
        {blocks.isPending && <Skeleton className="h-40 w-full" />}
        {blocks.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            块清单加载失败：{blocks.error instanceof Error ? blocks.error.message : '请稍后重试。'}
          </p>
        )}
        <ul className="flex max-h-72 flex-col gap-1.5 overflow-y-auto">
          {allBlocks.map((b) => (
            <li key={b.id}>
              <label className="flex items-start gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2 text-xs">
                <input
                  type="checkbox"
                  checked={selected.has(b.id)}
                  onChange={() => toggle(b.id)}
                  aria-label={`保留块：${b.id}`}
                  className="mt-0.5"
                />
                <span className="min-w-0 flex-1 line-clamp-3 text-[var(--lumi-text-secondary)]">{b.text}</span>
              </label>
            </li>
          ))}
        </ul>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">修订说明（可选）</span>
          <input
            type="text"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            aria-label="修订说明"
            className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2 text-sm text-[var(--lumi-text-primary)]"
          />
        </label>
        {noneSelected && (
          <p role="status" className="text-xs text-[var(--lumi-warning,--lumi-text-secondary)]">
            已移除全部块：保存需要显式确认（422 must_keep_one 保护仍在）。
          </p>
        )}
        {save.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {save.error instanceof Error ? save.error.message : '保存失败，请稍后重试。'}
          </p>
        )}
      </div>
    </Dialog>
  )
}

/** 详情头部：已修订徽标 + 查看原始 / 恢复原始。 */
export function ClipRevisionBadge({
  clipRef,
  revised,
  viewingOriginal,
  onToggleOriginal,
}: {
  clipRef: string
  revised: { revisedAt: string; note: string | null } | null | undefined
  viewingOriginal: boolean
  onToggleOriginal: () => void
}) {
  const queryClient = useQueryClient()
  const discard = useMutation({
    mutationFn: () => discardClipRevision(clipUuid(clipRef)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['library', 'clips'] })
    },
  })
  if (revised == null) return null
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs" data-clip-revised-badge="">
      <span
        className={cx(
          'inline-flex items-center gap-1 rounded-full px-2 py-0.5',
          'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-secondary)]',
        )}
      >
        <CheckCheck aria-hidden className="size-3" />
        已修订{revised.note ? `：${revised.note}` : ''}
      </span>
      <Button variant="ghost" size="sm" onClick={onToggleOriginal}>
        <History aria-hidden className="mr-1 inline size-3" />
        {viewingOriginal ? '返回修订版' : '查看原始版本'}
      </Button>
      {viewingOriginal && (
        <Button variant="ghost" size="sm" disabled={discard.isPending} onClick={() => discard.mutate()}>
          恢复原始（丢弃修订）
        </Button>
      )}
      {discard.isError && (
        <span role="alert" className="text-[var(--lumi-danger)]">
          {discard.error instanceof Error ? discard.error.message : '恢复失败。'}
        </span>
      )}
    </div>
  )
}

/** 原始正文 HTML 的净化渲染（查看原始版本时使用；同服务端管线）。 */
export function safeOriginalHtml(original: Record<string, unknown> | undefined | null): string {
  const html = typeof original?.contentHtml === 'string' ? original.contentHtml : ''
  return sanitizeArticleHtml(html)
}
