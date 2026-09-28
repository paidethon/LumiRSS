/** NEW-232 失效标注重定位 — 用户为漂移批注手动选新段落重锚。
 * 输入新段落定位（paraId + 可选新引文）；旧引文与旧位置由服务端永久
 * 保留（append-only 历史），这里同时展示历史供追溯。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { listReanchorHistory, reanchorAnnotation } from '../../api/new231'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/Skeleton'

export function AnnotationReanchorPanel({ annotationId }: { annotationId: string }) {
  const queryClient = useQueryClient()
  const [paraId, setParaId] = useState('')
  const [excerpt, setExcerpt] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const history = useQuery({
    queryKey: ['new231-reanchor-history', annotationId],
    queryFn: ({ signal }) => listReanchorHistory(annotationId, signal),
  })

  const reanchorMutation = useMutation({
    mutationFn: () =>
      reanchorAnnotation(
        annotationId,
        { paraId: paraId.trim() },
        excerpt.trim() === '' ? undefined : excerpt.trim(),
      ),
    onSuccess: async () => {
      setParaId('')
      setExcerpt('')
      setNotice('已重锚；旧引文与旧位置已永久保留在历史。')
      await queryClient.invalidateQueries({ queryKey: ['new231-reanchor-history', annotationId] })
      await queryClient.invalidateQueries({ queryKey: ['annotations-manager'] })
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '重锚失败'),
  })

  return (
    <section aria-label="失效标注重定位（NEW-232）" className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">重新锚定选中标注</h3>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">NEW-232 · 旧位置永不覆盖</span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          value={paraId}
          onChange={(event) => setParaId(event.target.value)}
          placeholder="新段落定位（如 block-7）"
          aria-label="新段落定位"
          className="min-w-0 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-sm"
        />
        <input
          type="text"
          value={excerpt}
          onChange={(event) => setExcerpt(event.target.value)}
          placeholder="新引文（可空 = 保留旧摘录）"
          aria-label="新引文"
          className="min-w-0 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-sm"
        />
        <Button
          size="sm"
          variant="secondary"
          disabled={paraId.trim() === '' || reanchorMutation.isPending}
          onClick={() => reanchorMutation.mutate()}
        >
          重锚到此段
        </Button>
      </div>

      {history.isPending && <Skeleton className="h-8 w-full" />}
      {history.data && history.data.items.length > 0 && (
        <ul className="flex flex-col gap-1" aria-label="重锚历史">
          {history.data.items.map((entry) => (
            <li key={entry.id} className="text-xs text-[var(--lumi-text-tertiary)]">
              {entry.reanchoredAt}：{String(entry.oldAnchor.paraId ?? '?')} →{' '}
              {String(entry.newAnchor.paraId ?? '?')}
              {entry.oldExcerpt ? `（旧引文「${entry.oldExcerpt.slice(0, 20)}…」已保留）` : ''}
            </li>
          ))}
        </ul>
      )}
      {history.data && history.data.items.length === 0 && (
        <p className="text-xs text-[var(--lumi-text-tertiary)]">该标注从未重锚。</p>
      )}

      {notice !== null && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">{notice}</p>
      )}
    </section>
  )
}
