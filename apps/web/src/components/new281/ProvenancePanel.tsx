/** NEW-287 简报人工精选标记 — 草稿条目的编辑来源（人工选入 / 规则推荐）
 * 如实展示与翻转；确认后不可翻转（读者已按确认稿阅读）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { flipProvenance, listBriefings } from '../../api/new281'
import {
  NoteText,
  StatusLine,
  errorText,
  secondaryButtonClass,
} from './parts'

export function ProvenancePanel() {
  const queryClient = useQueryClient()
  const [notice, setNotice] = useState<string | null>(null)

  const issues = useQuery({
    queryKey: ['new281-issues'],
    queryFn: ({ signal }) => listBriefings(signal),
  })
  const drafts = issues.data?.issues.filter((issue) => issue.status === 'draft') ?? []

  const flipMutation = useMutation({
    mutationFn: ({ issueId, itemId, provenance }: { issueId: string; itemId: string; provenance: 'manual' | 'rule' }) =>
      flipProvenance(issueId, itemId, provenance),
    onSuccess: async (issue) => {
      setNotice(`「${issue.title}」的编辑来源已更新。`)
      await queryClient.invalidateQueries({ queryKey: ['new281-issues'] })
    },
    onError: (error) => setNotice(errorText(error)),
  })

  const firstDraft = drafts[0]
  const detail = useQuery({
    queryKey: ['new281-issue', firstDraft?.id],
    enabled: Boolean(firstDraft),
    queryFn: async () => {
      const response = await fetch(`/api/v1/briefings/${firstDraft.id}`)
      if (!response.ok) throw new Error(`请求失败（${response.status}）`)
      return (await response.json()) as import('../../api/new281').Briefing
    },
  })

  return (
    <div className="flex flex-col gap-3">
      <NoteText>
        编辑来源随条目保存并展示给读者（RSS / EML / 详情一致）：<strong>编辑选入</strong> =
        你亲手挑的；<strong>规则推荐</strong> = 生成规则选的，采纳后如实保留标记。确认后的期次不可翻转。
      </NoteText>
      {issues.isError && <StatusLine tone="error">{errorText(issues.error)}</StatusLine>}
      {drafts.length === 0 && <NoteText>没有草稿期次——编辑来源的翻转只在草稿期可用。</NoteText>}
      {firstDraft && detail.data && (
        <ul className="flex flex-col gap-2" data-new281-provenance-list="">
          {detail.data.items.map((item) => (
            <li
              key={item.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1.5"
            >
              <span className="text-sm text-[var(--lumi-text-primary)]">
                <span
                  className={
                    item.provenance === 'manual'
                      ? 'text-[var(--lumi-accent)]'
                      : 'text-[var(--lumi-warning)]'
                  }
                >
                  【{item.provenanceLabel}】
                </span>
                {item.title}
              </span>
              <button
                type="button"
                className={secondaryButtonClass}
                disabled={flipMutation.isPending}
                onClick={() =>
                  flipMutation.mutate({
                    issueId: detail.data.id,
                    itemId: item.id,
                    provenance: item.provenance === 'manual' ? 'rule' : 'manual',
                  })
                }
              >
                翻转为{item.provenance === 'manual' ? '规则推荐' : '编辑选入'}
              </button>
            </li>
          ))}
        </ul>
      )}
      {notice && <StatusLine tone={flipMutation.isError ? 'error' : 'ok'}>{notice}</StatusLine>}
    </div>
  )
}
