/** NEW-281 个人简报编排台 — 时间范围/来源/栏目选卡，排成一期简报，
 * 可预览、修改（整稿替换）和保存（确认）。已刊过条目内联给出 282
 * 去重决定；截稿窗口开启时迟到条目须显式调回（283）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  confirmBriefing,
  createBriefing,
  fetchCandidates,
  fetchWindow,
  listBriefings,
  type CandidateCard,
} from '../../api/new281'
import {
  NoteText,
  StatusLine,
  buttonClass,
  errorText,
  inputClass,
  secondaryButtonClass,
  TextField,
} from './parts'

/** 近 N 天的 ISO 时间（相对 now，不写死日期）。 */
function isoDaysAgo(days: number): string {
  return new Date(Date.now() - days * 86400000).toISOString()
}

export function ComposerPanel() {
  const queryClient = useQueryClient()
  const [rangeFrom, setRangeFrom] = useState(isoDaysAgo(3))
  const [rangeTo, setRangeTo] = useState(isoDaysAgo(0))
  const [feedUrl, setFeedUrl] = useState('')
  const [title, setTitle] = useState('')
  const [sectionLabel, setSectionLabel] = useState('正文')
  const [picked, setPicked] = useState<Map<string, CandidateCard>>(new Map())
  const [decisions, setDecisions] = useState<Map<string, 'include' | 'defer' | 'skip'>>(new Map())
  const [pullBacks, setPullBacks] = useState<Set<string>>(new Set())
  const [notice, setNotice] = useState<string | null>(null)

  // 283：窗口开启时，截稿点之后的条目须显式勾选「调回」才能进本期。
  const windowQuery = useQuery({
    queryKey: ['new281-window'],
    queryFn: ({ signal }) => fetchWindow(signal),
  })
  const cutoffUtc = windowQuery.data?.configured ? windowQuery.data.cutoffUtc : undefined
  const isLate = (card: CandidateCard) =>
    Boolean(cutoffUtc && card.publishedAt && card.publishedAt >= cutoffUtc)

  const candidates = useQuery({
    queryKey: ['new281-candidates', rangeFrom, rangeTo, feedUrl],
    queryFn: ({ signal }) => fetchCandidates(rangeFrom, rangeTo, feedUrl, signal),
    enabled: Boolean(rangeFrom && rangeTo),
  })

  const issues = useQuery({
    queryKey: ['new281-issues'],
    queryFn: ({ signal }) => listBriefings(signal),
  })

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['new281-issues'] })
    await queryClient.invalidateQueries({ queryKey: ['new281-candidates'] })
    await queryClient.invalidateQueries({ queryKey: ['new281-followups'] })
  }

  const toggle = (card: CandidateCard) => {
    setPicked((prev) => {
      const next = new Map(prev)
      if (next.has(card.entryRef)) next.delete(card.entryRef)
      else next.set(card.entryRef, card)
      return next
    })
  }

  const createMutation = useMutation({
    mutationFn: async () => {
      const cards = [...picked.values()]
      if (!title.trim()) throw new Error('先给这期简报起个标题。')
      if (cards.length === 0) throw new Error('至少选择一篇文章（空刊不可创建）。')
      const key = 'main'
      return createBriefing({
        title: title.trim(),
        rangeFrom,
        rangeTo,
        sections: [{ key, label: sectionLabel.trim() || '正文' }],
        items: cards.map((card) => ({
          entryRef: card.entryRef,
          sectionKey: key,
          title: card.title,
          feedTitle: card.feedTitle,
          url: card.url,
          publishedAt: card.publishedAt,
          excerpt: card.excerpt,
          ...(isLate(card) ? { pullBack: pullBacks.has(card.entryRef) } : {}),
          ...(card.seenInIssues.length > 0 ? { dupDecision: decisions.get(card.entryRef) ?? 'include' } : {}),
        })),
      })
    },
    onSuccess: async (issue) => {
      setPicked(new Map())
      setDecisions(new Map())
      setTitle('')
      setNotice(`已建草稿「${issue.title}」（${issue.items.length} 条），可在下方确认保存。`)
      await invalidate()
    },
    onError: (error) => setNotice(errorText(error)),
  })

  const confirmMutation = useMutation({
    mutationFn: (issueId: string) => confirmBriefing(issueId),
    onSuccess: async (issue) => {
      setNotice(`「${issue.title}」已确认保存（确认后可 RSS 发布 / EML 导出 / 追加更正）。`)
      await invalidate()
    },
    onError: (error) => setNotice(errorText(error)),
  })

  return (
    <div className="flex flex-col gap-3">
      <NoteText>
        候选卡来自你的真实订阅（时间范围 [起, 止)），只取标题/来源/链接/摘录。以前期次收录过的条目会标出，
        由你决定重收、仅列后续或跳过——系统绝不静默重收。
      </NoteText>
      <div className="grid gap-2 sm:grid-cols-2">
        <TextField label="范围起（ISO 时间）" value={rangeFrom} onChange={setRangeFrom} />
        <TextField label="范围止（ISO 时间，不含）" value={rangeTo} onChange={setRangeTo} />
        <TextField label="限定来源 URL（可选，留空 = 全部来源）" value={feedUrl} onChange={setFeedUrl} />
        <TextField label="本期标题" value={title} onChange={setTitle} placeholder="例如：周三晨报" />
        <TextField label="栏目名（本组 UI 单栏目；多栏目用配方+生成）" value={sectionLabel} onChange={setSectionLabel} />
      </div>
      <button
        type="button"
        className={secondaryButtonClass}
        onClick={() => void candidates.refetch()}
      >
        拉取候选摘要卡
      </button>
      {candidates.isError && <StatusLine tone="error">{errorText(candidates.error)}</StatusLine>}
      {candidates.data && candidates.data.count === 0 && (
        <StatusLine tone="info">这个范围里没有文章——调整范围或先刷新订阅。</StatusLine>
      )}
      {candidates.data && candidates.data.count > 0 && (
        <ul className="flex flex-col gap-2" data-new281-candidates="">
          {candidates.data.candidates.map((card) => {
            const isPicked = picked.has(card.entryRef)
            const seen = card.seenInIssues.length > 0
            return (
              <li
                key={card.entryRef}
                data-new281-card={card.entryRef}
                className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2"
              >
                <label className="flex items-start gap-2 text-sm text-[var(--lumi-text-primary)]">
                  <input
                    type="checkbox"
                    aria-label={`选入：${card.title}`}
                    checked={isPicked}
                    onChange={() => toggle(card)}
                  />
                  <span>
                    <span className="font-medium">{card.title}</span>
                    <span className="ml-1 text-xs text-[var(--lumi-text-tertiary)]">
                      {card.feedTitle} · {card.publishedAt}
                      {card.starred ? ' · 已标星' : ''}
                    </span>
                  </span>
                </label>
                {card.excerpt && (
                  <p className="text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">{card.excerpt}</p>
                )}
                {isLate(card) && (
                  <label className="flex items-center gap-2 text-xs text-[var(--lumi-warning)]">
                    <input
                      type="checkbox"
                      aria-label={`调回本期（迟到）：${card.title}`}
                      checked={pullBacks.has(card.entryRef)}
                      onChange={() =>
                        setPullBacks((prev) => {
                          const next = new Set(prev)
                          if (next.has(card.entryRef)) next.delete(card.entryRef)
                          else next.add(card.entryRef)
                          return next
                        })
                      }
                    />
                    截稿点（{cutoffUtc}）之后发布——勾选「调回」才进本期，否则属下一期
                  </label>
                )}
                {seen && (
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs text-[var(--lumi-warning)]">
                      已在「{card.seenInIssues[0].issueTitle}」收录过
                    </span>
                    <select
                      aria-label={`重复决定：${card.title}`}
                      value={decisions.get(card.entryRef) ?? 'include'}
                      onChange={(event) =>
                        setDecisions((prev) => {
                          const next = new Map(prev)
                          next.set(card.entryRef, event.target.value as 'include' | 'defer' | 'skip')
                          return next
                        })
                      }
                      className={inputClass}
                    >
                      <option value="include">重收（再进本期）</option>
                      <option value="defer">仅列后续（不进正文）</option>
                      <option value="skip">跳过</option>
                    </select>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
      <button
        type="button"
        className={buttonClass}
        disabled={createMutation.isPending}
        onClick={() => createMutation.mutate()}
      >
        建草稿（{picked.size} 条已选）
      </button>
      {notice && <StatusLine tone={createMutation.isError ? 'error' : 'ok'}>{notice}</StatusLine>}

      <section aria-label="期次列表" className="flex flex-col gap-2">
        <h4 className="text-sm font-medium text-[var(--lumi-text-primary)]">期次</h4>
        {issues.isError && <StatusLine tone="error">{errorText(issues.error)}</StatusLine>}
        {issues.data?.issues.length === 0 && <NoteText>还没有期次——先编排一期。</NoteText>}
        {issues.data?.issues.map((issue) => (
          <div
            key={issue.id}
            data-new281-issue={issue.id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1.5"
          >
            <span className="text-sm text-[var(--lumi-text-primary)]">
              {issue.title} · {issue.itemCount} 条 ·{' '}
              <span className="text-xs text-[var(--lumi-text-tertiary)]">
                {issue.status === 'confirmed' ? `已确认 ${issue.confirmedAt ?? ''}` : '草稿'}
              </span>
            </span>
            {issue.status === 'draft' && (
              <button
                type="button"
                className={secondaryButtonClass}
                disabled={confirmMutation.isPending}
                onClick={() => confirmMutation.mutate(issue.id)}
              >
                确认保存
              </button>
            )}
          </div>
        ))}
      </section>
    </div>
  )
}
