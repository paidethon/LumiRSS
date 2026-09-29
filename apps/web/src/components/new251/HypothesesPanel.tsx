/** NEW-252 假设登记册 — 待检验假设（支持/反驳条件必填）+ 材料分配。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  addHypothesisMaterial,
  createHypothesis,
  listHypotheses,
  patchHypothesis,
  type Hypothesis,
} from '../../api/new251'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { ErrorLine, NoticeLine, SelectField, StatusBadge, TextAreaField, TextField } from './parts'


function HypothesisCard({ hyp }: { hyp: Hypothesis }) {
  const queryClient = useQueryClient()
  const [ref, setRef] = useState('')
  const [side, setSide] = useState<'support' | 'refute'>('support')
  const [notice, setNotice] = useState<string | null>(null)

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['new252-hypotheses'] })

  const statusMutation = useMutation({
    mutationFn: (status: Hypothesis['status']) => patchHypothesis(hyp.id, { status }),
    onSuccess: async () => {
      setNotice('裁决已记录（用户显式判定）。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '裁决失败'),
  })
  const materialMutation = useMutation({
    mutationFn: () => addHypothesisMaterial(hyp.id, { itemRef: ref, side }),
    onSuccess: async (result) => {
      setNotice(result.outcome === 'duplicate' ? '该侧已挂同一材料（幂等）。' : '材料已分配到对应侧。')
      setRef('')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '分配失败'),
  })

  return (
    <li data-new252-hypothesis={hyp.id} className="flex flex-col gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium text-[var(--lumi-text-primary)]">{hyp.statement}</p>
        <StatusBadge status={hyp.status} />
      </div>
      <p className="text-xs text-[var(--lumi-text-secondary)]">可支持条件：{hyp.supportCondition}</p>
      <p className="text-xs text-[var(--lumi-text-secondary)]">可反驳条件：{hyp.refuteCondition}</p>
      {hyp.materials.length > 0 && (
        <ul className="flex flex-wrap gap-1">
          {hyp.materials.map((material) => (
            <li
              key={material.id}
              className="rounded-[var(--lumi-radius-sm)] border border-[var(--lumi-border)] px-1.5 py-0.5 text-xs text-[var(--lumi-text-tertiary)]"
            >
              {material.side === 'support' ? '支持' : '反驳'}：{material.itemRef.slice(0, 24)}…
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-40 flex-1">
          <TextField label="分配材料 ItemRef" value={ref} onChange={setRef} placeholder="rss:… / library:…" />
        </div>
        <SelectField
          label="分配到"
          value={side}
          onChange={(value) => setSide(value === 'refute' ? 'refute' : 'support')}
          options={[
            { value: 'support', label: '支持侧' },
            { value: 'refute', label: '反驳侧' },
          ]}
        />
        <Button size="sm" onClick={() => materialMutation.mutate()} disabled={materialMutation.isPending}>
          分配材料
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => statusMutation.mutate('supported')}
          disabled={statusMutation.isPending}
        >
          判定支持
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => statusMutation.mutate('refuted')}
          disabled={statusMutation.isPending}
        >
          判定反驳
        </Button>
      </div>
      <NoticeLine notice={notice} />
    </li>
  )
}

export function HypothesesPanel({ projectId }: { projectId: string }) {
  const [statement, setStatement] = useState('')
  const [supportCondition, setSupportCondition] = useState('')
  const [refuteCondition, setRefuteCondition] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const hypotheses = useQuery({
    queryKey: ['new252-hypotheses', projectId],
    queryFn: ({ signal }) => listHypotheses(projectId, signal),
  })

  const createMutation = useMutation({
    mutationFn: () => createHypothesis(projectId, { statement, supportCondition, refuteCondition }),
    onSuccess: async () => {
      setStatement('')
      setSupportCondition('')
      setRefuteCondition('')
      setNotice('假设已登记（可反驳条件是登记门槛）。')
      await hypotheses.refetch()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '登记失败'),
  })

  const items = hypotheses.data?.items ?? []
  return (
    <div data-new252-hypotheses="" className="flex flex-col gap-3">
      <div className="flex flex-col gap-2">
        <TextAreaField label="假设陈述" value={statement} onChange={setStatement} placeholder="待检验的命题" />
        <TextField
          label="可支持条件（什么证据能支持它）"
          value={supportCondition}
          onChange={setSupportCondition}
        />
        <TextField
          label="可反驳条件（什么证据能推翻它）"
          value={refuteCondition}
          onChange={setRefuteCondition}
        />
        <div>
          <Button size="sm" onClick={() => createMutation.mutate()} disabled={createMutation.isPending}>
            登记假设
          </Button>
        </div>
      </div>
      <NoticeLine notice={notice} />
      <ErrorLine error={hypotheses.error} />
      {hypotheses.isPending && <p className="text-xs text-[var(--lumi-text-tertiary)]">加载假设…</p>}
      {hypotheses.data !== undefined && items.length === 0 && (
        <EmptyState title="尚无假设" description="登记可检验的假设，材料随后分配到支持/反驳两侧。" />
      )}
      <ul className="flex flex-col gap-2">
        {items.map((hyp) => (
          <HypothesisCard key={hyp.id} hyp={hyp} />
        ))}
      </ul>
    </div>
  )
}
