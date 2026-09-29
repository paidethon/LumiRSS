/** NEW-259 结论变更记录 — 修改项目结论时保留原结论、触发材料与新表述。
 *
 * 台账只追加：服务端没有 UPDATE/DELETE 路径（见 new259_conclusion_history.py），
 * 这里每次修改都会在历史里多一行 oldText → newText；回看历史即回看当时
 * 如实登记的内容，本面板不提供任何「改历史」入口（诚实边界：不覆盖历史）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  getConclusionHistory,
  getCurrentConclusion,
  setConclusion,
} from '../../api/new251'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { ErrorLine, NoticeLine, TextAreaField, TextField } from './parts'

export function ConclusionHistoryPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const [text, setText] = useState('')
  const [triggerRefs, setTriggerRefs] = useState('')
  const [reason, setReason] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const current = useQuery({
    queryKey: ['new259-conclusion', projectId],
    queryFn: ({ signal }) => getCurrentConclusion(projectId, signal),
  })
  const history = useQuery({
    queryKey: ['new259-conclusion-history', projectId],
    queryFn: ({ signal }) => getConclusionHistory(projectId, signal),
  })

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['new259-conclusion', projectId] })
    await queryClient.invalidateQueries({ queryKey: ['new259-conclusion-history', projectId] })
  }

  const setMutation = useMutation({
    mutationFn: () => {
      const refs = triggerRefs
        .split(/[,，\s]+/)
        .map((raw) => raw.trim())
        .filter((raw) => raw.length > 0)
      return setConclusion(projectId, {
        text,
        triggerRefs: refs.length > 0 ? refs : undefined,
        reason: reason.trim().length > 0 ? reason.trim() : undefined,
      })
    },
    onSuccess: async (result) => {
      setText('')
      setTriggerRefs('')
      setReason('')
      setNotice(
        result.previousText === null
          ? '结论已首次登记（台账记 oldText=空，诚实表示此前未登记）。'
          : '结论已更新，原结论保留在台账。',
      )
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '登记失败'),
  })

  return (
    <div data-new259-conclusion="" className="flex flex-col gap-3">
      <div className="flex flex-col gap-2">
        {current.data?.text !== null && current.data?.text !== undefined && (
          <p className="text-xs text-[var(--lumi-text-secondary)]">
            当前结论：{current.data.text}
          </p>
        )}
        <TextAreaField label="新结论（手写文本，服务端不做任何自动归纳）" value={text} onChange={setText} rows={3} />
        <TextField
          label="触发材料 ItemRef（可选，逗号分隔）"
          value={triggerRefs}
          onChange={setTriggerRefs}
          placeholder="rss:… / library:…"
        />
        <TextField label="修改原因（可选）" value={reason} onChange={setReason} />
        <div>
          <Button size="sm" onClick={() => setMutation.mutate()} disabled={setMutation.isPending}>
            登记新结论
          </Button>
        </div>
      </div>
      <NoticeLine notice={notice} />
      <ErrorLine error={current.error ?? history.error} />
      {history.data !== undefined && history.data.items.length === 0 && (
        <EmptyState title="尚无变更台账" description="首次登记结论也会进台账（原结论记为空）。" />
      )}
      <ol className="flex flex-col gap-2">
        {(history.data?.items ?? []).map((change) => (
          <li
            key={change.id}
            data-new259-change={change.id}
            className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2"
          >
            <p className="text-xs text-[var(--lumi-text-secondary)]">
              <span className="text-[var(--lumi-text-tertiary)]">{change.changedAt.slice(0, 19).replace('T', ' ')}</span>
              {' · '}
              原结论：{change.oldText ?? '（此前未登记）'}
            </p>
            <p className="text-sm text-[var(--lumi-text-primary)]">→ {change.newText}</p>
            {change.triggerRefs.length > 0 && (
              <p className="text-xs text-[var(--lumi-text-tertiary)]">触发材料：{change.triggerRefs.join('，')}</p>
            )}
            {change.reason !== null && (
              <p className="text-xs text-[var(--lumi-text-tertiary)]">原因：{change.reason}</p>
            )}
          </li>
        ))}
      </ol>
    </div>
  )
}
