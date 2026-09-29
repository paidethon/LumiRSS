/** NEW-254 研究术语表 — 项目私有术语 + 查词（阅读时主动调出）。
 *
 * 查不到诚实显示未收录；绝不触碰全局词典（服务端 glossary 表零交互）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  createResearchTerm,
  listResearchGlossary,
  lookupResearchTerm,
  patchResearchTerm,
} from '../../api/new251'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { ErrorLine, NoticeLine, TextAreaField, TextField } from './parts'

export function ResearchGlossaryPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const [term, setTerm] = useState('')
  const [interpretation, setInterpretation] = useState('')
  const [source, setSource] = useState('')
  const [lookupTerm, setLookupTerm] = useState('')
  const [lookupResult, setLookupResult] = useState<{ found: boolean; text: string } | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const glossary = useQuery({
    queryKey: ['new254-glossary', projectId],
    queryFn: ({ signal }) => listResearchGlossary(projectId, signal),
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['new254-glossary', projectId] })

  const createMutation = useMutation({
    mutationFn: () =>
      createResearchTerm(projectId, {
        term,
        interpretation,
        source: source || undefined,
      }),
    onSuccess: async () => {
      setTerm('')
      setInterpretation('')
      setSource('')
      setNotice('术语已收录（同项目同名只保留当前采用解释）。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '收录失败'),
  })
  const lookupMutation = useMutation({
    mutationFn: () => lookupResearchTerm(projectId, lookupTerm),
    onSuccess: (result) => {
      setLookupResult({
        found: result.found,
        text: result.found && result.match !== null
          ? `${result.match.term}：${result.match.interpretation}`
          : `「${result.term}」未收录在本项目术语表。`,
      })
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '查词失败'),
  })
  const patchMutation = useMutation({
    mutationFn: (args: { id: string; interpretation: string }) =>
      patchResearchTerm(args.id, { interpretation: args.interpretation }),
    onSuccess: async () => {
      setNotice('解释已更新（当前采用语义）。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '更新失败'),
  })

  const items = glossary.data?.items ?? []
  return (
    <div data-new254-glossary="" className="flex flex-col gap-3">
      <div className="flex items-end gap-2">
        <div className="min-w-40 flex-1">
          <TextField label="查词（阅读时主动调出）" value={lookupTerm} onChange={setLookupTerm} />
        </div>
        <Button size="sm" onClick={() => lookupMutation.mutate()} disabled={lookupMutation.isPending}>
          查词
        </Button>
      </div>
      {lookupResult !== null && (
        <p role="status" data-new254-lookup="" className="text-xs text-[var(--lumi-text-secondary)]">
          {lookupResult.found ? '✓ ' : '∅ '}
          {lookupResult.text}
        </p>
      )}
      <div className="flex flex-col gap-2 border-t border-[var(--lumi-border)] pt-3">
        <TextField label="术语" value={term} onChange={setTerm} />
        <TextAreaField label="采用的解释" value={interpretation} onChange={setInterpretation} />
        <TextField label="出处（可选）" value={source} onChange={setSource} />
        <div>
          <Button size="sm" onClick={() => createMutation.mutate()} disabled={createMutation.isPending}>
            收录术语
          </Button>
        </div>
      </div>
      <NoticeLine notice={notice} />
      <ErrorLine error={glossary.error} />
      {glossary.isPending && <p className="text-xs text-[var(--lumi-text-tertiary)]">加载术语…</p>}
      {glossary.data !== undefined && items.length === 0 && (
        <EmptyState title="术语表为空" description="为这个项目定义你采用的术语解释，不影响全局词典。" />
      )}
      <ul className="flex flex-col gap-2">
        {items.map((item) => (
          <li key={item.id} data-new254-term={item.id} className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
            <p className="text-sm font-medium text-[var(--lumi-text-primary)]">{item.term}</p>
            <p className="text-xs text-[var(--lumi-text-secondary)]">{item.interpretation}</p>
            {item.source !== null && (
              <p className="text-xs text-[var(--lumi-text-tertiary)]">出处：{item.source}</p>
            )}
            <TermEditor
              current={item.interpretation}
              onSave={(value) => patchMutation.mutate({ id: item.id, interpretation: value })}
              pending={patchMutation.isPending}
            />
          </li>
        ))}
      </ul>
    </div>
  )
}

function TermEditor({
  current,
  onSave,
  pending,
}: {
  current: string
  onSave: (value: string) => void
  pending: boolean
}) {
  const [value, setValue] = useState('')
  return (
    <div className="mt-2 flex items-end gap-2">
      <div className="min-w-40 flex-1">
        <TextField
          label="改解释（当前采用语义）"
          value={value}
          onChange={setValue}
          placeholder={current.slice(0, 20)}
        />
      </div>
      <Button size="sm" variant="ghost" onClick={() => onSave(value)} disabled={pending}>
        保存解释
      </Button>
    </div>
  )
}
