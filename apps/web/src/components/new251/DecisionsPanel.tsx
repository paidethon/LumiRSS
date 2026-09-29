/** NEW-256 研究决策记录 — 基于材料作个人决策 + 只追加 followups。
 *
 * 决策行登记后不可改写（服务端无 PATCH）；错了就追加 revision 说明。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  addDecisionFollowUp,
  addDecisionMaterial,
  createDecision,
  listDecisions,
} from '../../api/new251'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { ErrorLine, NoticeLine, SelectField, TextAreaField, TextField } from './parts'

export function DecisionsPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const [decision, setDecision] = useState('')
  const [basis, setBasis] = useState('')
  const [refsDraft, setRefsDraft] = useState('')
  const [followupDrafts, setFollowupDrafts] = useState<Record<string, string>>({})
  const [followupKinds, setFollowupKinds] = useState<Record<string, string>>({})
  const [materialDrafts, setMaterialDrafts] = useState<Record<string, string>>({})
  const [notice, setNotice] = useState<string | null>(null)

  const decisions = useQuery({
    queryKey: ['new256-decisions', projectId],
    queryFn: ({ signal }) => listDecisions(projectId, signal),
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['new256-decisions', projectId] })

  const createMutation = useMutation({
    mutationFn: () =>
      createDecision(projectId, {
        decision,
        basis: basis || undefined,
        itemRefs: refsDraft
          .split(/[\s,]+/)
          .map((item) => item.trim())
          .filter((item) => item !== ''),
      }),
    onSuccess: async () => {
      setDecision('')
      setBasis('')
      setRefsDraft('')
      setNotice('决策已登记（登记后不可改写，只能追加结果/修正）。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '登记失败'),
  })
  const followupMutation = useMutation({
    mutationFn: (args: { decisionId: string; kind: 'outcome' | 'revision'; text: string }) =>
      addDecisionFollowUp(args.decisionId, { kind: args.kind, text: args.text }),
    onSuccess: async () => {
      setNotice('已追加（只追加，历史可回看）。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '追加失败'),
  })
  const materialMutation = useMutation({
    mutationFn: (args: { decisionId: string; itemRef: string }) =>
      addDecisionMaterial(args.decisionId, args.itemRef),
    onSuccess: async () => {
      setNotice('依据材料已补挂。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '补挂失败'),
  })

  const items = decisions.data?.items ?? []
  return (
    <div data-new256-decisions="" className="flex flex-col gap-3">
      <div className="flex flex-col gap-2">
        <TextAreaField label="决策内容（必填）" value={decision} onChange={setDecision} />
        <TextAreaField label="决策依据说明" value={basis} onChange={setBasis} />
        <TextField
          label="依据材料 ItemRef（空格或逗号分隔，可留空）"
          value={refsDraft}
          onChange={setRefsDraft}
          placeholder="rss:… library:…"
        />
        <div>
          <Button size="sm" onClick={() => createMutation.mutate()} disabled={createMutation.isPending}>
            登记决策
          </Button>
        </div>
      </div>
      <NoticeLine notice={notice} />
      <ErrorLine error={decisions.error} />
      {decisions.isPending && <p className="text-xs text-[var(--lumi-text-tertiary)]">加载决策…</p>}
      {decisions.data !== undefined && items.length === 0 && (
        <EmptyState title="尚无决策记录" description="记下「基于哪些材料作了哪项决定」，后续追加结果。" />
      )}
      <ul className="flex flex-col gap-2">
        {items.map((item) => (
          <li key={item.id} data-new256-decision={item.id} className="flex flex-col gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
            <p className="text-sm font-medium text-[var(--lumi-text-primary)]">{item.decision}</p>
            {item.basis !== null && (
              <p className="text-xs text-[var(--lumi-text-secondary)]">依据：{item.basis}</p>
            )}
            {item.materials.length > 0 && (
              <p className="text-xs text-[var(--lumi-text-tertiary)]">
                依据材料 {item.materials.length} 条（{item.materials[0].itemRef.slice(0, 20)}… 等）
              </p>
            )}
            {item.followUps.length > 0 && (
              <ul className="flex flex-col gap-1 border-l-2 border-[var(--lumi-border)] pl-2">
                {item.followUps.map((followUp) => (
                  <li key={followUp.id} className="text-xs text-[var(--lumi-text-secondary)]">
                    [{followUp.kind === 'outcome' ? '结果' : '修正'}] {followUp.text}
                  </li>
                ))}
              </ul>
            )}
            <div className="flex flex-wrap items-end gap-2">
              <SelectField
                label="追加类型"
                value={followupKinds[item.id] ?? 'outcome'}
                onChange={(value) => setFollowupKinds((prev) => ({ ...prev, [item.id]: value }))}
                options={[
                  { value: 'outcome', label: '结果' },
                  { value: 'revision', label: '修正原因' },
                ]}
              />
              <div className="min-w-40 flex-1">
                <TextField
                  label="追加内容"
                  value={followupDrafts[item.id] ?? ''}
                  onChange={(value) => setFollowupDrafts((prev) => ({ ...prev, [item.id]: value }))}
                />
              </div>
              <Button
                size="sm"
                onClick={() =>
                  followupMutation.mutate({
                    decisionId: item.id,
                    kind: followupKinds[item.id] === 'revision' ? 'revision' : 'outcome',
                    text: followupDrafts[item.id] ?? '',
                  })
                }
                disabled={followupMutation.isPending}
              >
                追加
              </Button>
              <div className="min-w-40 flex-1">
                <TextField
                  label="补挂依据材料"
                  value={materialDrafts[item.id] ?? ''}
                  onChange={(value) => setMaterialDrafts((prev) => ({ ...prev, [item.id]: value }))}
                  placeholder="rss:… / library:…"
                />
              </div>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => materialMutation.mutate({ decisionId: item.id, itemRef: materialDrafts[item.id] ?? '' })}
                disabled={materialMutation.isPending}
              >
                补挂材料
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
