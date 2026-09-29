/** NEW-253 反例收集视图 — 冲突证据单独立项收集 + 显式处理。
 *
 * 处理时必须回答「结论是否调整」；真正的结论修改走 NEW-259——本面板
 * 不提供任何直接改项目结论的入口。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  attachCounterexampleSource,
  createCounterexample,
  listCounterexamples,
  resolveCounterexample,
} from '../../api/new251'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { ErrorLine, NoticeLine, SelectField, StatusBadge, TextAreaField, TextField } from './parts'

function ResolveForm({ id, onDone }: { id: string; onDone: () => void }) {
  const queryClient = useQueryClient()
  const [adjusted, setAdjusted] = useState<string>('no')
  const [resolutionNote, setResolutionNote] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const resolveMutation = useMutation({
    mutationFn: () =>
      resolveCounterexample(id, {
        conclusionAdjusted: adjusted === 'yes',
        resolutionNote,
      }),
    onSuccess: async () => {
      setNotice('处理已记录（含「结论是否调整」的显式回答）。')
      await queryClient.invalidateQueries({ queryKey: ['new253-counterexamples'] })
      onDone()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '处理失败'),
  })

  return (
    <div data-new253-resolve={id} className="flex flex-col gap-2 border-t border-[var(--lumi-border)] pt-2">
      <SelectField
        label="结论是否调整"
        value={adjusted}
        onChange={setAdjusted}
        options={[
          { value: 'no', label: '不调整（证据不足以推翻）' },
          { value: 'yes', label: '调整（去 NEW-259 登记新表述）' },
        ]}
      />
      <TextAreaField label="处理说明（必填）" value={resolutionNote} onChange={setResolutionNote} />
      <div>
        <Button size="sm" onClick={() => resolveMutation.mutate()} disabled={resolveMutation.isPending}>
          标记已处理
        </Button>
      </div>
      <NoticeLine notice={notice} />
    </div>
  )
}

export function CounterexamplesPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const [excerpt, setExcerpt] = useState('')
  const [note, setNote] = useState('')
  const [sourceDrafts, setSourceDrafts] = useState<Record<string, string>>({})
  const [resolving, setResolving] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const counterexamples = useQuery({
    queryKey: ['new253-counterexamples', projectId],
    queryFn: ({ signal }) => listCounterexamples(projectId, signal),
  })

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['new253-counterexamples', projectId] })

  const createMutation = useMutation({
    mutationFn: () => createCounterexample(projectId, { excerpt, note: note || undefined }),
    onSuccess: async () => {
      setExcerpt('')
      setNote('')
      setNotice('反例已收集（出处可以后补）。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '收集失败'),
  })
  const sourceMutation = useMutation({
    mutationFn: (args: { id: string; itemRef: string }) => attachCounterexampleSource(args.id, args.itemRef),
    onSuccess: async () => {
      setNotice('出处已后补。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '后补失败'),
  })

  const items = counterexamples.data?.items ?? []
  return (
    <div data-new253-counterexamples="" className="flex flex-col gap-3">
      <div className="flex flex-col gap-2">
        <TextAreaField label="冲突原文摘录（必填）" value={excerpt} onChange={setExcerpt} />
        <TextField label="备注（可选）" value={note} onChange={setNote} />
        <div>
          <Button size="sm" onClick={() => createMutation.mutate()} disabled={createMutation.isPending}>
            收集反例
          </Button>
        </div>
      </div>
      <NoticeLine notice={notice} />
      <ErrorLine error={counterexamples.error} />
      {counterexamples.data !== undefined && (
        <p className="text-xs text-[var(--lumi-text-tertiary)]">
          未处理 {counterexamples.data.unhandledCount} 条 · 已处理 {counterexamples.data.handledCount} 条
        </p>
      )}
      {counterexamples.data !== undefined && items.length === 0 && (
        <EmptyState title="尚无反例" description="读到与现有结论冲突的原文时，先把证据抄录在这里。" />
      )}
      <ul className="flex flex-col gap-2">
        {items.map((item) => (
          <li key={item.id} className="flex flex-col gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm text-[var(--lumi-text-primary)]">{item.excerpt}</p>
              <StatusBadge status={item.status} />
            </div>
            <p className="text-xs text-[var(--lumi-text-tertiary)]">
              {item.itemRef === null ? '出处未挂（可后补）' : `出处：${item.itemRef.slice(0, 30)}…`}
            </p>
            {item.status === 'handled' && item.resolutionNote !== null && (
              <p className="text-xs text-[var(--lumi-text-secondary)]">
                处理说明：{item.resolutionNote}（结论{item.conclusionAdjusted ? '已' : '未'}调整）
              </p>
            )}
            {item.status === 'unhandled' && resolving !== item.id && (
              <div className="flex items-end gap-2">
                <div className="min-w-40 flex-1">
                  <TextField
                    label="后补出处 ItemRef"
                    value={sourceDrafts[item.id] ?? ''}
                    onChange={(value) => setSourceDrafts((prev) => ({ ...prev, [item.id]: value }))}
                    placeholder="rss:… / library:…"
                  />
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    sourceMutation.mutate({ id: item.id, itemRef: sourceDrafts[item.id] ?? '' })
                  }
                  disabled={sourceMutation.isPending}
                >
                  后补出处
                </Button>
                <Button size="sm" onClick={() => setResolving(item.id)}>
                  处理
                </Button>
              </div>
            )}
            {item.status === 'unhandled' && resolving === item.id && (
              <ResolveForm id={item.id} onDone={() => setResolving(null)} />
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
