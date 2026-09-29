/** NEW-243 原始 feed 字段查看器 — 脱敏原始字段 + 应用映射说明，
 * 逐字段可报告错误映射（只追加台账，不自动改映射）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { createRawFieldReport, getRawFields, listRawFieldReports } from '../../api/new241'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/Skeleton'

export function RawFieldsPanel({ entryRef }: { entryRef: string }) {
  const queryClient = useQueryClient()
  const [fieldKey, setFieldKey] = useState('')
  const [problem, setProblem] = useState('')
  const [expected, setExpected] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const fields = useQuery({
    queryKey: ['new243-raw-fields', entryRef],
    queryFn: ({ signal }) => getRawFields(entryRef, signal),
  })
  const reports = useQuery({
    queryKey: ['new243-raw-field-reports', entryRef],
    queryFn: ({ signal }) => listRawFieldReports(entryRef, signal),
  })

  const reportMutation = useMutation({
    mutationFn: () => createRawFieldReport(entryRef, fieldKey, problem, expected),
    onSuccess: async () => {
      setNotice('报告已记录（只追加台账，不自动改任何映射）。')
      setProblem('')
      setExpected('')
      await queryClient.invalidateQueries({ queryKey: ['new243-raw-field-reports', entryRef] })
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '报告提交失败'),
  })

  return (
    <section
      aria-label="原始 feed 字段查看器（NEW-243）"
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
    >
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">原始 feed 字段查看器</h3>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">NEW-243</span>
      </div>

      {fields.isPending && <Skeleton className="h-16 w-full" />}
      {fields.isError && (
        <div role="alert" className="text-xs text-[var(--lumi-text-secondary)]">
          {fields.error instanceof Error && fields.error.message.includes('404')
            ? '投影中没有这篇文章，没有原始字段可看。'
            : `字段加载失败。${fields.error instanceof Error ? fields.error.message : ''}`}
        </div>
      )}
      {fields.data && (
        <ul className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
          {fields.data.fields.map((field) => (
            <li key={field.key} className="flex flex-col gap-0.5">
              <span className="text-[var(--lumi-text-primary)]">{field.key}</span>
              <span>{field.present ? String(field.value) : '（原始字段缺失）'}</span>
              <span className="text-[var(--lumi-text-tertiary)]">
                应用映射：{field.appMapping}；来源：{field.sourceDescription}
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-col gap-1 border-t border-[var(--lumi-border)] pt-2">
        <input
          aria-label="报告字段名"
          value={fieldKey}
          onChange={(event) => setFieldKey(event.target.value)}
          placeholder="字段名，例如 title"
          className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
        />
        <input
          aria-label="映射问题描述"
          value={problem}
          onChange={(event) => setProblem(event.target.value)}
          placeholder="哪里映射错了"
          className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
        />
        <input
          aria-label="期望映射说明"
          value={expected}
          onChange={(event) => setExpected(event.target.value)}
          placeholder="期望应是什么（可空）"
          className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
        />
        <Button
          size="sm"
          variant="secondary"
          className="self-start"
          disabled={fieldKey.trim() === '' || problem.trim() === '' || reportMutation.isPending}
          onClick={() => reportMutation.mutate()}
        >
          报告错误映射
        </Button>
      </div>

      {reports.data && reports.data.items.length > 0 && (
        <ul className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
          {reports.data.items.map((item) => (
            <li key={item.id}>
              {item.fieldKey}：{item.problem}
              {item.expected !== '' ? `（期望：${item.expected}）` : ''}
            </li>
          ))}
        </ul>
      )}

      {notice !== null && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
          {notice}
        </p>
      )}
    </section>
  )
}
