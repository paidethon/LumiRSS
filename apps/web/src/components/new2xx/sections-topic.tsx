/** NEW-230 队列重复主题提醒 section —— 自选主题标注 + 集中度报告。
 *
 * 主题由你手动标注（服务端绝不推断兴趣）；集中度只是提示，
 * 调换位置请用今日必读面板的排序——这里绝不自动重排。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { getQueueTopics, getTopicReport, setQueueTopics, type TopicReport } from './api'
import { Button } from '../ui/Button'
import { Chip, ErrorNote, ItemPicker, SectionShell, useTodayItems } from './parts'

export function TopicSection() {
  const qc = useQueryClient()
  const { items } = useTodayItems()
  const [ref, setRef] = useState('')
  const [raw, setRaw] = useState('')
  const [report, setReport] = useState<TopicReport | null>(null)
  const [error, setError] = useState<unknown>(null)

  const topicsQuery = useQuery({
    queryKey: ['new2xx', 'topics', ref],
    queryFn: ({ signal }) => getQueueTopics(ref, signal),
    enabled: ref !== '',
  })

  useEffect(() => {
    setRaw((topicsQuery.data?.topics ?? []).join('，'))
  }, [topicsQuery.data])

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['new2xx', 'topics'] })
  }

  const saveMutation = useMutation({
    mutationFn: () =>
      setQueueTopics(
        ref,
        raw
          .split(/[，,]/)
          .map((topic) => topic.trim())
          .filter(Boolean),
      ),
    onSuccess: invalidate,
    onError: setError,
  })
  const reportMutation = useMutation({
    mutationFn: () => getTopicReport(),
    onSuccess: (view) => {
      setReport(view)
      setError(null)
    },
    onError: setError,
  })

  return (
    <SectionShell
      title="队列重复主题提醒"
      hint="给队列文章标上你自己的主题；整理时看看主题集中度。要不要调换位置由你手动决定——这里绝不自动替你安排兴趣。"
    >
      <ErrorNote error={error} />
      <ItemPicker items={items} value={ref} onChange={setRef} label="文章" />
      {ref ? (
        <div className="flex items-end gap-2 text-xs">
          <label className="flex flex-1 flex-col gap-0.5 text-[var(--lumi-text-secondary)]">
            主题（逗号分隔，最多 5 个）
            <input
              value={raw}
              onChange={(event) => setRaw(event.target.value)}
              placeholder="如：AI，隐私"
              className="min-h-7 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-separator)] bg-[var(--lumi-surface-elevated)] px-2 py-0.5 text-xs"
            />
          </label>
          <Button size="sm" disabled={saveMutation.isPending} onClick={() => saveMutation.mutate()}>
            保存主题
          </Button>
        </div>
      ) : null}

      <div>
        <Button size="sm" variant="ghost" disabled={reportMutation.isPending} onClick={() => reportMutation.mutate()}>
          看今日主题集中度
        </Button>
      </div>

      {report ? (
        <div className="flex flex-col gap-1.5 text-xs">
          {report.topics.length === 0 ? (
            <p className="text-[var(--lumi-text-tertiary)]">
              今日队列还没有主题标注。给几篇标上主题再回来看。
            </p>
          ) : (
            report.topics.map((entry) => (
              <div
                key={entry.topic}
                className="flex flex-wrap items-center gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-separator)] px-2 py-1.5"
              >
                <span className="font-medium text-[var(--lumi-text-primary)]">{entry.topic}</span>
                <Chip tone={entry.itemCount > 1 ? 'warn' : 'neutral'}>{entry.itemCount} 篇</Chip>
                <span className="text-[var(--lumi-text-tertiary)]">
                  位置 {entry.positions.join('、')}
                  {entry.minGap !== null ? ` · 最近相隔 ${entry.minGap}` : ''}
                </span>
                {entry.itemCount > 1 ? (
                  <span className="ml-auto text-[var(--lumi-text-tertiary)]">
                    想集中或分散？去「今日必读」面板手动调换位置。
                  </span>
                ) : null}
              </div>
            ))
          )}
          <p className="text-[var(--lumi-text-tertiary)]">{report.note}</p>
        </div>
      ) : null}
    </SectionShell>
  )
}
