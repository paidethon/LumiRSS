/** SearchSessionPanel — NEW-367 搜索会话回溯。
 *
 * 「记录为研究步骤」= 新建（如无活动会话）或向活动会话追加当前查询；
 * 「选中结果」随步骤写入。重新打开接续到最后一步（resumeStep），
 * 点「接续」交给父级把最后一步的查询灌回搜索框。
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { History } from 'lucide-react'
import {
  appendSessionStep,
  createSearchSession,
  fetchSearchSessions,
  reopenSearchSession,
  setSessionSelections,
  type SearchSessionDetail,
} from '../../api/new361'
import { Button } from '../ui/Button'

const ACTIVE_SESSION_KEY = 'lumirss-new367-active-session'

function readActiveSessionId(): string | null {
  try {
    return sessionStorage.getItem(ACTIVE_SESSION_KEY)
  } catch {
    return null
  }
}

function writeActiveSessionId(id: string | null): void {
  try {
    if (id === null) sessionStorage.removeItem(ACTIVE_SESSION_KEY)
    else sessionStorage.setItem(ACTIVE_SESSION_KEY, id)
  } catch {
    /* 写失败不影响本会话 */
  }
}

export function SearchSessionPanel({
  query,
  filters,
  selectedRefs,
  onResumeStep,
}: {
  query: string
  filters: Record<string, unknown>
  /** 本页用户勾选的结果（NEW-367 语义：随最后一步保存）。 */
  selectedRefs: string[]
  onResumeStep: (stepQuery: string) => void
}) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [resumed, setResumed] = useState<SearchSessionDetail | null>(null)
  const sessions = useQuery({
    queryKey: ['new367', 'sessions'],
    queryFn: () => fetchSearchSessions(),
    enabled: open,
  })
  const record = useMutation({
    mutationFn: async () => {
      let sessionId = readActiveSessionId()
      if (sessionId === null) {
        const created = await createSearchSession(
          `研究：${query.slice(0, 20) || '未命名'}`,
        )
        sessionId = created.id
        writeActiveSessionId(sessionId)
      }
      const detail = await appendSessionStep(sessionId, query, filters)
      if (selectedRefs.length > 0) {
        return setSessionSelections(sessionId, selectedRefs)
      }
      return detail
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['new367', 'sessions'] })
    },
  })
  const reopen = useMutation({
    mutationFn: (sessionId: string) => reopenSearchSession(sessionId),
    onSuccess: (detail) => setResumed(detail),
  })

  return (
    <section
      data-testid="n367-sessions"
      aria-label="搜索会话回溯"
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3"
    >
      <button
        type="button"
        aria-expanded={open}
        data-testid="n367-toggle"
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-7 items-center gap-1.5 text-left text-xs font-medium text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-accent-text)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
      >
        <History aria-hidden className="size-3.5" />
        搜索会话回溯
      </button>
      <div className="flex flex-wrap gap-1.5">
        <Button
          size="sm"
          variant="secondary"
          data-testid="n367-record"
          disabled={record.isPending || query.trim() === ''}
          onClick={() => record.mutate()}
        >
          记录为研究步骤
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={record.isPending}
          onClick={() => {
            writeActiveSessionId(null)
            record.reset()
          }}
        >
          结束当前会话
        </Button>
      </div>
      {record.isSuccess && (
        <p role="status" data-testid="n367-recorded" className="text-xs text-[var(--lumi-text-secondary)]">
          已记录（当前第 {record.data.stepCount} 步
          {selectedRefs.length > 0 ? `，含 ${selectedRefs.length} 条选中结果` : ''}）。
        </p>
      )}
      {record.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          记录失败：{record.error instanceof Error ? record.error.message : '请稍后重试。'}
        </p>
      )}
      {open && (
        <ul className="flex flex-col gap-1" data-testid="n367-session-list">
          {(sessions.data?.items ?? []).map((session) => (
            <li key={session.id} className="flex items-center justify-between gap-2">
              <span className="truncate text-xs text-[var(--lumi-text-secondary)]">
                {session.title}（{session.stepCount} 步）
              </span>
              <Button
                size="sm"
                variant="ghost"
                disabled={reopen.isPending}
                onClick={() => reopen.mutate(session.id)}
              >
                重新打开
              </Button>
            </li>
          ))}
          {sessions.data !== undefined && sessions.data.items.length === 0 && (
            <li className="text-xs text-[var(--lumi-text-tertiary)]">还没有会话。</li>
          )}
        </ul>
      )}
      {resumed !== null && (
        <div data-testid="n367-resumed" className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-selected)] p-2">
          <p className="text-xs text-[var(--lumi-text-secondary)]">
            已接续「{resumed.title}」到最后一步（第 {resumed.resumeStep + 1} 步）
            {resumed.steps[resumed.resumeStep] !== undefined &&
              `：${resumed.steps[resumed.resumeStep].query}`}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {resumed.steps[resumed.resumeStep] !== undefined && (
              <Button
                size="sm"
                variant="secondary"
                onClick={() =>
                  onResumeStep(resumed.steps[resumed.resumeStep].query)
                }
              >
                接续该查询
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={() => setResumed(null)}>
              收起
            </Button>
          </div>
        </div>
      )}
    </section>
  )
}
