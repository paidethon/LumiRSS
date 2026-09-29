/** NEW-292 会话串联 / NEW-293 引用折叠 — 按真实字段自动成串的手动
 * 兜底（并入选定目标），与阅读时引用段折叠 + 逐段核对。 */

import { useCallback, useEffect, useState } from 'react'
import {
  getQuoteSegments,
  linkThread,
  markQuoteReviewed,
  type QuoteSegmentsView,
  type ThreadView,
} from '../../api/new291'
import { NoteText, StatusLine, buttonClass, errorText, inputClass } from './panel'

export function ThreadPanel({ materialId }: { materialId: string }) {
  const [targetId, setTargetId] = useState('')
  const [thread, setThread] = useState<ThreadView | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function link(): Promise<void> {
    setBusy(true)
    setError('')
    try {
      setThread(await linkThread(materialId, targetId.trim()))
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-new291-thread="" className="flex flex-col gap-3">
      <label className="flex flex-col gap-1">
        <span className="text-sm text-[var(--lumi-text-secondary)]">关联到的目标条目 ID（字段不足时的手动兜底）</span>
        <input
          type="text"
          className={inputClass}
          value={targetId}
          onChange={(e) => setTargetId(e.target.value)}
          placeholder="eml-…"
        />
      </label>
      <button type="button" className={buttonClass} disabled={busy || targetId.trim() === ''} onClick={() => void link()}>
        手动关联成会话
      </button>
      {thread !== null && (
        <div data-new291-thread-view="" className="flex flex-col gap-1">
          <StatusLine tone="ok">会话 {thread.threadId}：{thread.members.length} 封</StatusLine>
          <ul className="flex flex-col gap-0.5">
            {thread.members.map((m) => (
              <li key={m.id} className="text-sm leading-relaxed text-[var(--lumi-text-secondary)]">
                {m.subject || '（无主题）'}（{m.linkMode === 'references' ? '按头部字段' : '手动'}）
              </li>
            ))}
          </ul>
          <NoteText>{thread.honestyNote}</NoteText>
        </div>
      )}
      {error !== '' && <StatusLine tone="error">{error}</StatusLine>}
    </div>
  )
}

export function QuoteFoldPanel({ materialId }: { materialId: string }) {
  const [view, setView] = useState<QuoteSegmentsView | null>(null)
  const [expanded, setExpanded] = useState<number[]>([])
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    try {
      setView(await getQuoteSegments(materialId))
    } catch (err) {
      setError(errorText(err))
    }
  }, [materialId])

  useEffect(() => {
    void refresh()
  }, [refresh])

  function toggleExpand(index: number): void {
    setExpanded((prev) => (prev.includes(index) ? prev.filter((i) => i !== index) : [...prev, index]))
  }

  async function review(index: number): Promise<void> {
    setError('')
    try {
      setView(await markQuoteReviewed(materialId, index))
    } catch (err) {
      setError(errorText(err))
    }
  }

  if (error !== '') return <StatusLine tone="error">{error}</StatusLine>
  if (view === null) return <StatusLine tone="info">载入中…</StatusLine>
  return (
    <div data-new291-quotes="" className="flex flex-col gap-2">
      <StatusLine tone="info">
        引用段 {view.quotedCount} 个（共 {view.quotedLines} 行）默认折叠；已核对 {view.reviewedCount}
      </StatusLine>
      {view.segments.map((segment) =>
        segment.kind === 'own' ? (
          <p key={segment.index} className="whitespace-pre-wrap text-sm leading-relaxed text-[var(--lumi-text-primary)]">
            {segment.text}
          </p>
        ) : (
          <div key={segment.index} className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
            <div className="flex items-center gap-2">
              <button
                type="button"
                aria-expanded={expanded.includes(segment.index)}
                onClick={() => toggleExpand(segment.index)}
                className="text-sm text-[var(--lumi-accent)] underline underline-offset-2"
              >
                引用段 {segment.index + 1}（{segment.lines} 行）
              </button>
              {segment.reviewed ? (
                <span className="text-sm text-[var(--lumi-success)]">已核对</span>
              ) : (
                <button
                  type="button"
                  className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-0.5 text-sm text-[var(--lumi-text-primary)] hover:bg-[var(--lumi-surface-hover)]"
                  onClick={() => void review(segment.index)}
                >
                  标为已核对
                </button>
              )}
            </div>
            {expanded.includes(segment.index) && (
              <pre className="whitespace-pre-wrap text-sm leading-relaxed text-[var(--lumi-text-tertiary)]">{segment.text}</pre>
            )}
          </div>
        ),
      )}
      <NoteText>{view.honestyNote}</NoteText>
    </div>
  )
}
