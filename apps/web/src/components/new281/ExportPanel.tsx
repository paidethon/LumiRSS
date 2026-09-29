/** NEW-289 简报纯文本邮件文件 — 确认期次导出为 EML 附件下载（绝不发送，
 * 不需要 SMTP 凭据；发送与否由用户拿文件后自行决定）。 */

import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { exportEml, listBriefings } from '../../api/new281'
import {
  NoteText,
  SelectField,
  StatusLine,
  buttonClass,
  errorText,
} from './parts'

export function ExportPanel() {
  const [issueId, setIssueId] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const issues = useQuery({
    queryKey: ['new281-issues'],
    queryFn: ({ signal }) => listBriefings(signal),
  })
  const confirmed = issues.data?.issues.filter((issue) => issue.status === 'confirmed') ?? []

  const exportMutation = useMutation({
    mutationFn: () => exportEml(issueId),
    onSuccess: (result) => {
      setNotice(`已导出 ${result.filename}（${result.size} 字节）到你的下载目录——文件由你检查后自行处理，系统绝不发送邮件。`)
    },
    onError: (error) => setNotice(errorText(error)),
  })

  return (
    <div className="flex flex-col gap-3">
      <NoteText>
        导出的是可检查的 RFC 5322 文件（正文含编辑来源标记与更正提示）。这里没有 SMTP、没有发送动作——
        拿到文件后发不发、发到哪，完全由你决定。草稿不可导出（先确认）。
      </NoteText>
      {issues.isError && <StatusLine tone="error">{errorText(issues.error)}</StatusLine>}
      <SelectField
        label="已确认的期次"
        value={issueId}
        onChange={setIssueId}
        options={[
          { value: '', label: '（选择一期）' },
          ...confirmed.map((issue) => ({ value: issue.id, label: `${issue.title}（${issue.itemCount} 条）` })),
        ]}
      />
      <button
        type="button"
        className={buttonClass}
        disabled={!issueId || exportMutation.isPending}
        onClick={() => exportMutation.mutate()}
      >
        导出 EML 文件
      </button>
      {notice && <StatusLine tone={exportMutation.isError ? 'error' : 'ok'}>{notice}</StatusLine>}
    </div>
  )
}
