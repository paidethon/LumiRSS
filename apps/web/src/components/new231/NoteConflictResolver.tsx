/** NEW-239 标注冲突解决器 — 并排查看服务端版与另一台设备的待决编辑，
 * 用户选择保留任一份、保留两份（副本笔记）或手工合并。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  fetchConflictSides,
  resolveConflictRaw,
  type NoteConflictSide,
} from '../../api/new231'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'

export function NoteConflictResolver({ noteId }: { noteId: string }) {
  const queryClient = useQueryClient()
  const [notice, setNotice] = useState<string | null>(null)

  const sides = useQuery({
    queryKey: ['new231-conflict-sides', noteId],
    queryFn: ({ signal }) => fetchConflictSides(noteId, signal),
  })

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['new231-conflict-sides', noteId] })
    await queryClient.invalidateQueries({ queryKey: ['lumi-notes'] })
  }

  const resolveMutation = useMutation({
    mutationFn: async (input: { pendingId: string; resolution: string; merged?: { title: string; contentMd: string } }) =>
      resolveConflictRaw(noteId, input.pendingId, input.resolution, input.merged),
    onSuccess: async (result) => {
      if (result.ok) {
        setNotice('冲突已解决。')
        await invalidate()
      } else {
        setNotice(`解决失败（${result.status}）。`)
      }
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '解决失败'),
  })

  const pending = sides.data?.pending ?? []
  const server: NoteConflictSide | undefined = sides.data?.server

  return (
    <section aria-label="冲突解决器（NEW-239）" className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">冲突解决器</h3>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">NEW-239 · 另一台设备的编辑已暂存</span>
      </div>

      {sides.isPending && <Skeleton className="h-12 w-full" />}
      {!sides.isPending && pending.length === 0 && !sides.isError && (
        <EmptyState title="没有待解决的冲突" description="另一台设备提交过期编辑时会暂存在这里，供并排解决。" />
      )}

      {server && pending.length > 0 && (
        <div className="flex flex-col gap-2">
          {pending.map((item) => (
            <div key={item.id} className="grid grid-cols-2 gap-2" aria-label={`并排对比 ${item.deviceLabel || '另一设备'}`}>
              <div className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-hover)] p-2">
                <p className="text-xs font-medium text-[var(--lumi-text-primary)]">
                  本机（v{server.version}）
                </p>
                <pre className="max-h-32 overflow-auto whitespace-pre-wrap text-xs text-[var(--lumi-text-secondary)]">{server.contentMd}</pre>
              </div>
              <div className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-hover)] p-2">
                <p className="text-xs font-medium text-[var(--lumi-text-primary)]">
                  {item.deviceLabel || '另一设备'}（基于 v{item.baseVersion}）
                </p>
                <pre className="max-h-32 overflow-auto whitespace-pre-wrap text-xs text-[var(--lumi-text-secondary)]">{item.contentMd}</pre>
              </div>
              <div className="col-span-2 flex flex-wrap gap-1">
                <Button size="sm" variant="secondary" disabled={resolveMutation.isPending} onClick={() => resolveMutation.mutate({ pendingId: item.id, resolution: 'keep_server' })}>
                  保留本机
                </Button>
                <Button size="sm" variant="secondary" disabled={resolveMutation.isPending} onClick={() => resolveMutation.mutate({ pendingId: item.id, resolution: 'keep_pending' })}>
                  保留对方
                </Button>
                <Button size="sm" variant="secondary" disabled={resolveMutation.isPending} onClick={() => resolveMutation.mutate({ pendingId: item.id, resolution: 'keep_both' })}>
                  两份都保留（副本笔记）
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={resolveMutation.isPending}
                  onClick={() =>
                    resolveMutation.mutate({
                      pendingId: item.id,
                      resolution: 'merged',
                      merged: { title: server.title, contentMd: `${server.contentMd}\n${item.contentMd}` },
                    })
                  }
                >
                  手工合并（顺序拼接）
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {notice !== null && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">{notice}</p>
      )}
    </section>
  )
}
