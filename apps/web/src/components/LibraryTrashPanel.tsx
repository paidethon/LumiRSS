/** F019 Library 回收站面板 —— 列表 + 恢复 + 永久删除（二次确认）。
 *
 * 挂载时拉取回收站（bookmark + clip 两种 kind 合并展示）；恢复调用
 * restore（条目原样回到原列表并重新入搜索索引）；永久删除必须先经
 * 确认态（第二次点击才真正发 purge 请求——对应后端 permanent=true
 * 契约）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { AlertTriangle, Trash2 } from 'lucide-react'
import {
  listTrash,
  purgeTrashItem,
  restoreTrashItem,
  type TrashItem,
} from '../api/client'
import { Button } from './ui/Button'
import { EmptyState } from './ui/EmptyState'

export function LibraryTrashPanel({ onDone }: { onDone?: () => void }) {
  const queryClient = useQueryClient()
  const trash = useQuery({
    queryKey: ['library-trash'],
    queryFn: ({ signal }) => listTrash(undefined, signal),
  })
  const [confirming, setConfirming] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)

  const restore = useMutation({
    mutationFn: (uuid: string) => restoreTrashItem(uuid),
    onSuccess: async (_data, uuid) => {
      await queryClient.invalidateQueries({ queryKey: ['library-trash'] })
      await queryClient.invalidateQueries({ queryKey: ['bookmarks'] })
      await queryClient.invalidateQueries({ queryKey: ['clips'] })
      setFeedback('已恢复')
      setConfirming((current) => (current === uuid ? null : current))
      onDone?.()
    },
    onError: () => setFeedback('恢复失败，请重试'),
  })
  const purge = useMutation({
    mutationFn: (uuid: string) => purgeTrashItem(uuid),
    onSuccess: async (_data, uuid) => {
      await queryClient.invalidateQueries({ queryKey: ['library-trash'] })
      setFeedback('已永久删除')
      setConfirming((current) => (current === uuid ? null : current))
    },
    onError: () => setFeedback('永久删除失败，请重试'),
  })

  const items: TrashItem[] = trash.data?.items ?? []
  const busy = restore.isPending || purge.isPending

  return (
    <section
      aria-label="回收站"
      data-testid="trash-panel"
      className="mb-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
    >
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-[var(--lumi-text-primary)]">
        <Trash2 aria-hidden className="size-4" />
        回收站（{items.length}）
      </h3>
      {trash.isPending && <p className="mt-2 text-xs text-[var(--lumi-text-tertiary)]">加载中…</p>}
      {trash.isError && (
        <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">
          回收站加载失败，请重试。
        </p>
      )}
      {feedback !== null && (
        <p role="status" className="mt-1.5 text-xs text-[var(--lumi-accent-text)]">
          {feedback}
        </p>
      )}
      {items.length === 0 ? (
        <div className="mt-1">
          <EmptyState
            icon={<Trash2 aria-hidden className="size-6" />}
            title="回收站是空的"
            description="删除的书签与剪辑会先进入回收站（30 天后由清理任务过期）。"
          />
        </div>
      ) : (
        <ul className="mt-2 divide-y divide-[var(--lumi-separator)]">
          {items.map((item) => (
            <li key={item.uuid} className="flex flex-wrap items-center gap-2 py-1.5" data-testid="trash-item">
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm text-[var(--lumi-text-primary)]">{item.title}</span>
                <span className="block text-xs text-[var(--lumi-text-tertiary)]">
                  {item.kind === 'bookmark' ? '书签' : '剪辑'} · 删除于 {item.deletedAt.slice(0, 10)}
                </span>
              </span>
              <Button
                size="sm"
                variant="secondary"
                disabled={busy}
                onClick={() => restore.mutate(item.uuid)}
              >
                恢复
              </Button>
              {confirming === item.uuid ? (
                <span className="flex items-center gap-1">
                  <AlertTriangle aria-hidden className="size-3.5 text-[var(--lumi-danger)]" />
                  <Button
                    size="sm"
                    variant="danger"
                    disabled={busy}
                    onClick={() => purge.mutate(item.uuid)}
                  >
                    确认永久删除
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>
                    取消
                  </Button>
                </span>
              ) : (
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => setConfirming(item.uuid)}>
                  永久删除
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
