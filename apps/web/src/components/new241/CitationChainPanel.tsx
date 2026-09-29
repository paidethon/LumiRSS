/** NEW-246 资料来源链 — 手工登记「fromRef 引用了 toRef」，沿显式边追踪
 * 「本篇引用了什么」；中间缺环诚实标注，不推断未验证关系。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  createCitationEdge,
  deleteCitationEdge,
  listCitationEdges,
  traceCitationChain,
} from '../../api/new241'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/Skeleton'

export function CitationChainPanel({ entryRef }: { entryRef: string }) {
  const queryClient = useQueryClient()
  const [fromRef, setFromRef] = useState(entryRef)
  const [toRef, setToRef] = useState('')
  const [edgeNote, setEdgeNote] = useState('')
  const [traceRef, setTraceRef] = useState(entryRef)
  const [trace, setTrace] = useState<Awaited<ReturnType<typeof traceCitationChain>> | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const edges = useQuery({
    queryKey: ['new246-citation-edges'],
    queryFn: ({ signal }) => listCitationEdges(undefined, signal),
  })

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['new246-citation-edges'] })
  }

  const createMutation = useMutation({
    mutationFn: () => createCitationEdge(fromRef, toRef, edgeNote),
    onSuccess: async () => {
      setNotice('引用关系已登记（显式边）。')
      setToRef('')
      setEdgeNote('')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '登记失败'),
  })

  const traceMutation = useMutation({
    mutationFn: () => traceCitationChain(traceRef),
    onSuccess: (result) => setTrace(result),
    onError: (error) => setNotice(error instanceof Error ? error.message : '追踪失败'),
  })

  const deleteMutation = useMutation({
    mutationFn: (edgeId: string) => deleteCitationEdge(edgeId),
    onSuccess: async () => {
      setNotice('已解除该引用关系。')
      setTrace(null)
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '解除失败'),
  })

  const edgeItems = edges.data?.items ?? []

  return (
    <section
      aria-label="资料来源链（NEW-246）"
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
    >
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">资料来源链</h3>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">NEW-246</span>
      </div>

      <div className="flex flex-col gap-1">
        <div className="flex gap-1">
          <input
            aria-label="引用方 ref"
            value={fromRef}
            onChange={(event) => setFromRef(event.target.value)}
            placeholder="谁引用了（fromRef）"
            className="w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
          />
          <input
            aria-label="被引方 ref"
            value={toRef}
            onChange={(event) => setToRef(event.target.value)}
            placeholder="引用了什么（toRef）"
            className="w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
          />
        </div>
        <input
          aria-label="引用关系备注"
          value={edgeNote}
          onChange={(event) => setEdgeNote(event.target.value)}
          placeholder="备注（可空）"
          className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
        />
        <Button
          size="sm"
          variant="secondary"
          className="self-start"
          disabled={fromRef.trim() === '' || toRef.trim() === '' || createMutation.isPending}
          onClick={() => createMutation.mutate()}
        >
          登记引用关系
        </Button>
      </div>

      <div className="flex flex-col gap-1 border-t border-[var(--lumi-border)] pt-2">
        <div className="flex gap-1">
          <input
            aria-label="追踪起点 ref"
            value={traceRef}
            onChange={(event) => setTraceRef(event.target.value)}
            placeholder="从哪篇开始追踪引用链"
            className="w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
          />
          <Button
            size="sm"
            variant="secondary"
            disabled={traceRef.trim() === '' || traceMutation.isPending}
            onClick={() => traceMutation.mutate()}
          >
            追踪引用链
          </Button>
        </div>
        {trace !== null && (
          <ol className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]" aria-label="引用链结果">
            {trace.cycle && <li className="text-[var(--lumi-text-primary)]">检测到环：追踪已截断。</li>}
            {trace.truncated && <li className="text-[var(--lumi-text-primary)]">链条过长：已截断展示。</li>}
            {trace.chain.map((hop, index) => (
              <li key={`${hop.ref}-${index}`}>
                {index + 1}. {hop.ref}
                {hop.missingLink && '（中间环节缺失——下一跳没有显式登记，不推断）'}
              </li>
            ))}
          </ol>
        )}
      </div>

      {edges.isPending && <Skeleton className="h-8 w-full" />}
      {edges.isError && (
        <div role="alert" className="text-xs text-[var(--lumi-text-secondary)]">
          引用边加载失败。{edges.error instanceof Error ? edges.error.message : ''}
        </div>
      )}
      {edgeItems.length > 0 && (
        <ul className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
          {edgeItems.map((edge) => (
            <li key={edge.id} className="flex items-center gap-2">
              <span>
                {edge.fromRef} → {edge.toRef}
                {edge.note !== '' ? `（${edge.note}）` : ''}
              </span>
              <Button
                size="sm"
                variant="secondary"
                disabled={deleteMutation.isPending}
                onClick={() => deleteMutation.mutate(edge.id)}
              >
                解除
              </Button>
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
