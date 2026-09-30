/** RunbookPanel — NEW-398 错误自助处理单。
 *
 * 步骤是经过验证的用户侧处置（注册表随代码发布）；逐步记录效果
 * （tried/helped/no_effect/skipped），升级生成只含错误码 + 步骤结果 +
 * 备注 + 版本的脱敏求助材料。
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  escalateRunbookSession,
  fetchRunbooks,
  openRunbookSession,
  recordRunbookStep,
  type RunbookSessionDetail,
  type RunbookSpec,
} from '../../api/new391'
import { Button } from '../ui/Button'
import {
  NoteText,
  StatusLine,
  inputClass,
  labelClass,
} from './parts'

const OUTCOME_LABELS: Record<string, string> = {
  tried: '试过',
  helped: '有效',
  no_effect: '无效',
  skipped: '跳过',
}

function SessionView({
  session,
  onEscalated,
}: {
  session: RunbookSessionDetail
  onEscalated: (result: { id: string; status: string; material: RunbookSessionDetail['material'] }) => void
}) {
  const [escalateOpen, setEscalateOpen] = useState(false)
  const [note, setNote] = useState('')
  const queryClient = useQueryClient()
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['new391', 'runbooks'] })
  }
  const record = useMutation({
    mutationFn: (stepIndex: number) => recordRunbookStep(session.id, stepIndex, 'tried', ''),
    onSuccess: invalidate,
  })
  const escalate = useMutation({
    mutationFn: () => escalateRunbookSession(session.id, note.trim()),
    onSuccess: (result) => {
      setEscalateOpen(false)
      onEscalated(result)
      invalidate()
    },
    onError: () => setNote(''),
  })
  return (
    <div
      data-n391-session={session.id}
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3"
    >
      <span className="text-sm font-medium text-[var(--lumi-text-primary)]">
        {session.title}（{session.status === 'open' ? '进行中' : session.status === 'escalated' ? '已升级求助' : '已解决'}）
      </span>
      <ol className="flex flex-col gap-2">
        {session.steps.map((step) => {
          const outcome = session.outcomes.find((o) => o.stepIndex === step.index)
          return (
            <li key={step.index} data-n391-step={step.index} className="flex flex-col gap-1">
              <span className="text-sm text-[var(--lumi-text-primary)]">
                {step.index}. {step.title}
              </span>
              <NoteText>{step.detail}</NoteText>
              <div className="flex items-center gap-2">
                {outcome ? (
                  <StatusLine tone="info">
                    已记录：{OUTCOME_LABELS[outcome.outcome] ?? outcome.outcome}
                  </StatusLine>
                ) : (
                  <Button size="sm" loading={record.isPending} onClick={() => record.mutate(step.index)}>
                    记录「试过这步」
                  </Button>
                )}
              </div>
            </li>
          )
        })}
      </ol>
      {session.status === 'open' && (
        <div className="flex flex-col gap-1">
          {escalateOpen ? (
            <>
              <label className={labelClass} htmlFor={`escalate-note-${session.id}`}>
                求助备注（只写入脱敏材料，不含账户信息）
              </label>
              <input
                id={`escalate-note-${session.id}`}
                className={inputClass}
                value={note}
                onChange={(event) => setNote(event.target.value)}
              />
              <Button size="sm" loading={escalate.isPending} onClick={() => escalate.mutate()}>
                生成脱敏求助材料
              </Button>
            </>
          ) : (
            <Button size="sm" variant="ghost" onClick={() => setEscalateOpen(true)}>
              没解决，升级为求助材料
            </Button>
          )}
        </div>
      )}
      {session.material && (
        <div
          data-n391-material
          className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2"
        >
          <StatusLine tone="ok">求助材料已生成（脱敏）：</StatusLine>
          <NoteText>
            错误码 {session.material.code} · 版本 {session.material.version} ·{' '}
            {session.material.steps.length} 步结果 · 备注：{session.material.userNote}
          </NoteText>
        </div>
      )}
    </div>
  )
}

export function RunbookPanel() {
  const runbooks = useQuery({
    queryKey: ['new391', 'runbook-specs'],
    queryFn: fetchRunbooks,
  })
  const [session, setSession] = useState<RunbookSessionDetail | null>(null)
  const open = useMutation({
    mutationFn: (code: string) => openRunbookSession(code),
    onSuccess: (detail) => setSession(detail),
  })
  return (
    <div data-n391-panel="runbooks" className="flex flex-col gap-3">
      <NoteText>
        处理单只含经过验证的用户侧步骤；逐步记录效果，求助材料自动脱敏。
      </NoteText>
      {runbooks.data && (
        <ul className="flex flex-col gap-1">
          {runbooks.data.runbooks.map((book: RunbookSpec) => (
            <li
              key={book.code}
              data-n391-runbook={book.code}
              className="flex items-center justify-between gap-2"
            >
              <span className="text-sm text-[var(--lumi-text-primary)]">{book.title}</span>
              <Button
                size="sm"
                loading={open.isPending && open.variables === book.code}
                onClick={() => open.mutate(book.code)}
              >
                开始处理
              </Button>
            </li>
          ))}
        </ul>
      )}
      {session && (
        <SessionView
          session={session}
          onEscalated={(result) =>
            setSession((prev) =>
              prev ? { ...prev, status: 'escalated', material: result.material } : prev,
            )
          }
        />
      )}
    </div>
  )
}
