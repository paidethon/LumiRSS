/** NEW-231 笔记修订对照 — 快照 / 版本列表 / 逐行差异 / 恢复（留恢复记录）。
 *
 * 版本是显式快照（origin=manual/pre_restore/conflict）；恢复前服务端
 * 自动把当前版存为 pre_restore —— 恢复不销毁历史。恢复记录（restores）
 * 在台账里可查，UI 诚实展示来源 origin。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  diffNoteVersions,
  listNoteRestores,
  listNoteVersions,
  restoreNoteVersion,
  snapshotNoteVersion,
  type NoteVersionDiff,
} from '../../api/new231'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'

const ORIGIN_LABELS: Record<string, string> = {
  manual: '手动快照',
  pre_restore: '恢复前自动快照',
  conflict: '冲突解决前快照',
}

export function NoteVersionsPanel({ noteId }: { noteId: string }) {
  const queryClient = useQueryClient()
  const [fromRef, setFromRef] = useState<string>('')
  const [diff, setDiff] = useState<NoteVersionDiff | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const versions = useQuery({
    queryKey: ['new231-note-versions', noteId],
    queryFn: ({ signal }) => listNoteVersions(noteId, signal),
  })
  const restores = useQuery({
    queryKey: ['new231-note-restores', noteId],
    queryFn: ({ signal }) => listNoteRestores(noteId, signal),
  })

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['new231-note-versions', noteId] })
    await queryClient.invalidateQueries({ queryKey: ['new231-note-restores', noteId] })
  }

  const snapshotMutation = useMutation({
    mutationFn: () => snapshotNoteVersion(noteId),
    onSuccess: async () => {
      setNotice('已保存当前版快照。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '快照失败'),
  })
  const restoreMutation = useMutation({
    mutationFn: (versionId: string) => restoreNoteVersion(noteId, versionId),
    onSuccess: async (result) => {
      setNotice(`已恢复；恢复前内容已存为快照 ${result.preRestoreVersionId.slice(0, 8)}…`)
      await invalidate()
      await queryClient.invalidateQueries({ queryKey: ['lumi-notes'] })
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '恢复失败'),
  })
  const diffMutation = useMutation({
    mutationFn: async () => diffNoteVersions(noteId, fromRef),
    onSuccess: (result) => setDiff(result),
    onError: (error) => setNotice(error instanceof Error ? error.message : '差异计算失败'),
  })

  const versionItems = versions.data?.items ?? []

  return (
    <section aria-label="笔记修订对照（NEW-231）" className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">修订对照</h3>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">NEW-231</span>
        <div className="ml-auto">
          <Button size="sm" variant="secondary" disabled={snapshotMutation.isPending} onClick={() => snapshotMutation.mutate()}>
            保存当前版为快照
          </Button>
        </div>
      </div>

      {versions.isPending && <Skeleton className="h-16 w-full" />}
      {versions.isError && (
        <div role="alert" className="text-xs text-[var(--lumi-text-secondary)]">
          版本加载失败。{versions.error instanceof Error ? versions.error.message : ''}
        </div>
      )}
      {!versions.isPending && versionItems.length === 0 && !versions.isError && (
        <EmptyState title="还没有版本快照" description="「保存当前版为快照」后可逐行对比与恢复。" />
      )}

      {versionItems.length > 0 && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
            <label>
              对比版本
              <select
                aria-label="选择对比起始版本"
                value={fromRef}
                onChange={(event) => setFromRef(event.target.value)}
                className="ml-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1"
              >
                <option value="">选择…</option>
                {versionItems.map((item) => (
                  <option key={item.id} value={item.id}>
                    {(ORIGIN_LABELS[item.origin] ?? item.origin)} · {item.createdAt}
                  </option>
                ))}
              </select>
            </label>
            <Button size="sm" variant="secondary" disabled={fromRef === '' || diffMutation.isPending} onClick={() => diffMutation.mutate()}>
              与当前版对比
            </Button>
          </div>
          <ul className="flex flex-col gap-1" aria-label="版本列表">
            {versionItems.map((item) => (
              <li key={item.id} className="flex items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
                <span className="min-w-0 flex-1 truncate">
                  {(ORIGIN_LABELS[item.origin] ?? item.origin)} · {item.createdAt}
                </span>
                <Button size="sm" variant="ghost" disabled={restoreMutation.isPending} onClick={() => restoreMutation.mutate(item.id)}>
                  恢复此版
                </Button>
              </li>
            ))}
          </ul>
        </>
      )}

      {diff !== null && (
        <div className="flex flex-col gap-1">
          <p className="text-xs text-[var(--lumi-text-secondary)]">
            {diff.identical ? '两个版本内容一致。' : `+${diff.addedLines} 行 / -${diff.removedLines} 行`}
          </p>
          {!diff.identical && (
            <pre className="max-h-48 overflow-auto rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-hover)] p-2 text-xs" aria-label="版本差异">
              {diff.unified}
            </pre>
          )}
        </div>
      )}

      {restores.data && restores.data.items.length > 0 && (
        <p className="text-xs text-[var(--lumi-text-tertiary)]" aria-label="恢复记录">
          恢复记录：{restores.data.items.length} 次（最近 {restores.data.items[0].restoredAt}，来源
          {' '}{ORIGIN_LABELS[restores.data.items[0].versionOrigin] ?? restores.data.items[0].versionOrigin}）
        </p>
      )}

      {notice !== null && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">{notice}</p>
      )}
    </section>
  )
}
