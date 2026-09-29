/** NEW-262 译文人工修订层 — 逐段「放弃修订并重翻」的显式决定：
 * 只对有人工修订的段提供入口；放弃时刻的人工文本 + 机器原稿完整留底
 * （台账可回看）；可选立即按缓存源段重翻（只发该段）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { TranslationSegmentState } from '../../api/types'
import { discardRevision, listRevisionDecisions } from '../../api/new261'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { NoticeLine } from './parts'

export function RevisionDiscardPanel({ entryRef, segments }: { entryRef: string; segments: TranslationSegmentState[] }) {
  const queryClient = useQueryClient()
  const decisionsQuery = useQuery({
    queryKey: ['new262-revision-decisions', entryRef],
    queryFn: ({ signal }) => listRevisionDecisions(entryRef, signal),
  })
  const [regenerate, setRegenerate] = useState(true)
  const [notice, setNotice] = useState<string | null>(null)

  const revised = segments.filter((segment) => segment.userRevision)

  const discardMutation = useMutation({
    mutationFn: (blockIndex: number) => discardRevision(entryRef, blockIndex, regenerate),
    onSuccess: (result) => {
      const regen = result.regenerated
      setNotice(
        regen === null
          ? `已放弃第 ${result.blockIndex + 1} 段修订（原稿已留底），该段回到未生成。`
          : regen.status === 'success'
            ? `已放弃第 ${result.blockIndex + 1} 段修订并重翻成功${regen.cached ? '（缓存命中）' : ''}。`
            : `已放弃第 ${result.blockIndex + 1} 段修订；重翻未完成（${regen.status}${regen.reason ? `：${regen.reason}` : ''}）。`,
      )
      void queryClient.invalidateQueries({ queryKey: ['translation-segments', entryRef] })
      void queryClient.invalidateQueries({ queryKey: ['new262-revision-decisions', entryRef] })
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '放弃失败'),
  })

  return (
    <div className="flex flex-col gap-2">
      <label className="flex items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]">
        <input
          type="checkbox"
          checked={regenerate}
          onChange={(event) => setRegenerate(event.target.checked)}
          aria-label="放弃后立即重翻该段"
          className="size-3.5"
        />
        放弃后立即重翻该段
      </label>

      {revised.length === 0 && (
        <EmptyState title="没有人工修订段" description="当前只有机器译文（或尚未翻译）；修订过的段才会出现在这里。" />
      )}
      {revised.map((segment) => (
        <div
          key={segment.index}
          className="flex flex-wrap items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2 text-xs"
        >
          <span className="font-medium text-[var(--lumi-text-primary)]">第 {segment.index + 1} 段</span>
          <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-secondary)]">
            修订稿：{segment.userRevision}
          </span>
          <Button
            size="sm"
            variant="ghost"
            disabled={discardMutation.isPending}
            onClick={() => discardMutation.mutate(segment.index)}
          >
            放弃修订{regenerate ? '并重翻' : ''}
          </Button>
        </div>
      ))}

      {decisionsQuery.data && decisionsQuery.data.decisions.length > 0 && (
        <details className="text-xs text-[var(--lumi-text-secondary)]">
          <summary className="cursor-pointer">决定台账（{decisionsQuery.data.decisions.length} 条）</summary>
          <ul className="mt-1 flex flex-col gap-1">
            {decisionsQuery.data.decisions.map((decision) => (
              <li key={decision.id} className="rounded-[var(--lumi-radius-sm)] bg-[var(--lumi-surface-hover)] p-1.5">
                第 {decision.blockIndex + 1} 段 · 放弃于 {decision.createdAt} · 机器原稿已留底
              </li>
            ))}
          </ul>
        </details>
      )}

      {notice !== null && <NoticeLine tone={notice.includes('失败') || notice.includes('未完成') ? 'error' : 'success'}>{notice}</NoticeLine>}
    </div>
  )
}
