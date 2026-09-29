/** NEW-290 简报历史更正 — 追加式更正（只增不改不删；期次正文永不静默
 * 替换，读者在 RSS/EML/详情看到的是原文 + 更正提示）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { addCorrection, listBriefings, listCorrections } from '../../api/new281'
import {
  NoteText,
  SelectField,
  StatusLine,
  TextField,
  buttonClass,
  errorText,
} from './parts'

export function CorrectionPanel() {
  const queryClient = useQueryClient()
  const [issueId, setIssueId] = useState('')
  const [body, setBody] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const issues = useQuery({
    queryKey: ['new281-issues'],
    queryFn: ({ signal }) => listBriefings(signal),
  })
  const confirmed = issues.data?.issues.filter((issue) => issue.status === 'confirmed') ?? []

  const corrections = useQuery({
    queryKey: ['new281-corrections', issueId],
    enabled: Boolean(issueId),
    queryFn: ({ signal }) => listCorrections(issueId, signal),
  })

  const addMutation = useMutation({
    mutationFn: () => addCorrection(issueId, body.trim()),
    onSuccess: async () => {
      setNotice('更正已追加（原期次内容未做任何替换）。')
      setBody('')
      await queryClient.invalidateQueries({ queryKey: ['new281-corrections', issueId] })
    },
    onError: (error) => setNotice(errorText(error)),
  })

  return (
    <div className="flex flex-col gap-3">
      <NoteText>
        更正只增不改不删：期次正文永不静默替换，订阅者在 RSS / EML / 详情看到的是「原文 + 更正提示」。
        草稿没有已发布历史——直接编辑草稿即可。
      </NoteText>
      {issues.isError && <StatusLine tone="error">{errorText(issues.error)}</StatusLine>}
      <SelectField
        label="已确认的期次"
        value={issueId}
        onChange={setIssueId}
        options={[
          { value: '', label: '（选择一期）' },
          ...confirmed.map((issue) => ({ value: issue.id, label: issue.title })),
        ]}
      />
      {issueId && corrections.isError && <StatusLine tone="error">{errorText(corrections.error)}</StatusLine>}
      {issueId && corrections.data && corrections.data.count === 0 && (
        <NoteText>这一期还没有更正记录。</NoteText>
      )}
      {corrections.data && corrections.data.count > 0 && (
        <ul className="flex flex-col gap-1" data-new281-corrections="">
          {corrections.data.corrections.map((correction) => (
            <li
              key={correction.id}
              className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1.5 text-sm text-[var(--lumi-text-primary)]"
            >
              <span className="text-xs text-[var(--lumi-text-tertiary)]">{correction.createdAt}</span> —{' '}
              {correction.body}
            </li>
          ))}
        </ul>
      )}
      <TextField label="更正内容" value={body} onChange={setBody} placeholder="写清楚哪里有误、正确的是什么" />
      <button
        type="button"
        className={buttonClass}
        disabled={!issueId || !body.trim() || addMutation.isPending}
        onClick={() => addMutation.mutate()}
      >
        追加更正
      </button>
      {notice && <StatusLine tone={addMutation.isError ? 'error' : 'ok'}>{notice}</StatusLine>}
    </div>
  )
}
