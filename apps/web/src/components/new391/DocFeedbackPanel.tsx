/** DocFeedbackPanel — NEW-399 帮助文档反馈（用户侧 + 管理员队列）。
 *
 * 用户对具体帮助段落提问：docPath + 锚点自动携带提交时的构建版本与
 * 锚点检测结论；管理员定位版本与锚点、修订后回复，回复经 NEW-391
 * 落一条真实通知给作者。
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchAdminDocFeedback,
  fetchOwnDocFeedback,
  resolveDocFeedback,
  submitDocFeedback,
  type DocFeedbackEntry,
} from '../../api/new391'
import { Button } from '../ui/Button'
import {
  NoteText,
  StatusLine,
  inputClass,
  labelClass,
} from './parts'

function FeedbackRow({ entry }: { entry: DocFeedbackEntry }) {
  return (
    <li
      data-n391-feedback={entry.id}
      className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-medium text-[var(--lumi-text-primary)]">
          {entry.docPath}
          {entry.anchor && ` #${entry.anchor}`}
        </span>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">
          v{entry.version} ·{' '}
          {entry.status === 'open' ? '待处理' : '已修订'}
        </span>
      </div>
      {entry.anchorFound === false && (
        <StatusLine tone="info">锚点在当前文档里未找到（仍已提交）。</StatusLine>
      )}
      <NoteText>{entry.question}</NoteText>
      {entry.status === 'revised' && (
        <div className="flex flex-col gap-1">
          <StatusLine tone="ok">修订说明：{entry.revisionNote}</StatusLine>
          <NoteText>回复：{entry.reply}</NoteText>
        </div>
      )}
    </li>
  )
}

export function DocFeedbackPanel() {
  const [docPath, setDocPath] = useState('README.md')
  const [anchor, setAnchor] = useState('')
  const [question, setQuestion] = useState('')
  const [error, setError] = useState('')
  const queryClient = useQueryClient()
  const own = useQuery({
    queryKey: ['new391', 'own-feedback'],
    queryFn: fetchOwnDocFeedback,
  })
  const submit = useMutation({
    mutationFn: () =>
      submitDocFeedback({ docPath: docPath.trim(), anchor: anchor.trim(), question: question.trim() }),
    onSuccess: () => {
      setQuestion('')
      setError('')
      void own.refetch()
    },
    onError: () => setError('提交失败：文档路径必须相对 docs/ 且真实存在。'),
  })
  return (
    <div data-n391-panel="doc-feedback" className="flex flex-col gap-3">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-end gap-2">
          <div className="flex flex-col gap-1">
            <label className={labelClass} htmlFor="fb-doc">
              文档路径（相对 docs/）
            </label>
            <input
              id="fb-doc"
              className={inputClass}
              value={docPath}
              onChange={(event) => setDocPath(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className={labelClass} htmlFor="fb-anchor">
              锚点 / 小节标题（可选）
            </label>
            <input
              id="fb-anchor"
              className={inputClass}
              value={anchor}
              onChange={(event) => setAnchor(event.target.value)}
            />
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <label className={labelClass} htmlFor="fb-question">
            你的问题
          </label>
          <input
            id="fb-question"
            className={inputClass}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
          />
        </div>
        {error && <StatusLine tone="error">{error}</StatusLine>}
        <Button
          className="self-start"
          loading={submit.isPending}
          onClick={() => submit.mutate()}
        >
          提交反馈
        </Button>
      </div>
      {own.data && (
        <ul className="flex flex-col gap-2">
          {own.data.items.map((entry) => (
            <FeedbackRow key={entry.id} entry={entry} />
          ))}
        </ul>
      )}
    </div>
  )
}

export function AdminDocFeedbackQueue() {
  const [revisionNote, setRevisionNote] = useState('')
  const [reply, setReply] = useState('')
  const queryClient = useQueryClient()
  const queue = useQuery({
    queryKey: ['new391', 'admin-feedback'],
    queryFn: () => fetchAdminDocFeedback('open'),
  })
  const resolve = useMutation({
    mutationFn: ({ id }: { id: string }) =>
      resolveDocFeedback(id, revisionNote.trim(), reply.trim()),
    onSuccess: () => {
      setRevisionNote('')
      setReply('')
      void queryClient.invalidateQueries({ queryKey: ['new391', 'admin-feedback'] })
    },
  })
  if (queue.isLoading) {
    return (
      <div data-n391-panel="admin-feedback">
        <StatusLine tone="info">正在加载反馈队列…</StatusLine>
      </div>
    )
  }
  return (
    <div data-n391-panel="admin-feedback" className="flex flex-col gap-3">
      <NoteText>按提交时版本与锚点定位；修订后回复将通知作者（真实事件）。</NoteText>
      {queue.data && queue.data.items.length === 0 && (
        <NoteText>队列为空。</NoteText>
      )}
      <ul className="flex flex-col gap-2">
        {queue.data?.items.map((entry) => (
          <li
            key={entry.id}
            data-n391-admin-feedback={entry.id}
            className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3"
          >
            <span className="text-sm font-medium text-[var(--lumi-text-primary)]">
              {entry.docPath}
              {entry.anchor && ` #${entry.anchor}`} · v{entry.version}
            </span>
            <NoteText>{entry.question}</NoteText>
            <div className="flex flex-col gap-1">
              <label className={labelClass} htmlFor={`rn-${entry.id}`}>
                修订说明
              </label>
              <input
                id={`rn-${entry.id}`}
                className={inputClass}
                value={revisionNote}
                onChange={(event) => setRevisionNote(event.target.value)}
              />
              <label className={labelClass} htmlFor={`rp-${entry.id}`}>
                回复作者
              </label>
              <input
                id={`rp-${entry.id}`}
                className={inputClass}
                value={reply}
                onChange={(event) => setReply(event.target.value)}
              />
              <Button
                className="self-start"
                size="sm"
                loading={resolve.isPending}
                onClick={() => resolve.mutate({ id: entry.id })}
              >
                标记已修订并回复
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
