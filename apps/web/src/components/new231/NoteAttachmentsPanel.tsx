/** NEW-240 笔记附件清单 — 给笔记加本人选定的小附件，查看引用位置与
 * 容量；移除附件但保留文字笔记（正文由服务端保证不被触碰）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { addNoteAttachment, listNoteAttachments, removeNoteAttachment } from '../../api/new231'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  return `${(bytes / 1024).toFixed(1)} KB`
}

const MAX_FILE_BYTES = 256 * 1024

export function NoteAttachmentsPanel({ noteId }: { noteId: string }) {
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const attachments = useQuery({
    queryKey: ['new231-note-attachments', noteId],
    queryFn: ({ signal }) => listNoteAttachments(noteId, signal),
  })

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['new231-note-attachments', noteId] })
  }

  const addMutation = useMutation({
    mutationFn: async (file: File) => {
      const buffer = await file.arrayBuffer()
      if (buffer.byteLength > MAX_FILE_BYTES) {
        throw new Error('单个附件过大（≤256KB）。')
      }
      let binary = ''
      const bytes = new Uint8Array(buffer)
      for (let index = 0; index < bytes.length; index += 1) {
        binary += String.fromCharCode(bytes[index])
      }
      return addNoteAttachment(noteId, file.name, btoa(binary), file.type || undefined)
    },
    onSuccess: async () => {
      setNotice('附件已添加。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '添加失败'),
  })
  const removeMutation = useMutation({
    mutationFn: (attachmentId: string) => removeNoteAttachment(noteId, attachmentId),
    onSuccess: async () => {
      setNotice('附件已移除；文字笔记保留。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '移除失败'),
  })

  const items = attachments.data?.items ?? []
  const usage = attachments.data?.usage

  return (
    <section aria-label="笔记附件清单（NEW-240）" className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">附件清单</h3>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">NEW-240 · ≤256KB/个，≤1MB/笔记</span>
        {usage && (
          <span className="ml-auto text-xs text-[var(--lumi-text-secondary)]" aria-label="附件容量">
            {usage.count}/{usage.fileCapCount} 个 · {formatBytes(usage.totalBytes)}/{formatBytes(usage.noteCapBytes)}
          </span>
        )}
      </div>
      <div>
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          aria-hidden="true"
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) addMutation.mutate(file)
            event.target.value = ''
          }}
        />
        <Button size="sm" variant="secondary" disabled={addMutation.isPending} onClick={() => fileInputRef.current?.click()}>
          添加附件
        </Button>
      </div>

      {attachments.isPending && <Skeleton className="h-8 w-full" />}
      {!attachments.isPending && items.length === 0 && !attachments.isError && (
        <EmptyState title="还没有附件" description="可添加本人选定的小附件；移除附件不影响文字笔记。" />
      )}
      <ul className="flex flex-col gap-1" aria-label="附件列表">
        {items.map((item) => (
          <li key={item.id} className="flex items-center gap-2 text-xs">
            <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-primary)]">{item.filename}</span>
            <span className="shrink-0 text-[var(--lumi-text-tertiary)]">{formatBytes(item.sizeBytes)}</span>
            <a
              href={`/api/v1/library/notes/${encodeURIComponent(noteId)}/attachments/${encodeURIComponent(item.id)}/content`}
              download
              className="shrink-0 text-[var(--lumi-accent)] underline underline-offset-2"
              aria-label={`下载 ${item.filename}`}
            >
              下载
            </a>
            <Button size="sm" variant="ghost" aria-label={`移除附件 ${item.filename}`} disabled={removeMutation.isPending} onClick={() => removeMutation.mutate(item.id)}>
              移除
            </Button>
          </li>
        ))}
      </ul>

      {notice !== null && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">{notice}</p>
      )}
    </section>
  )
}
