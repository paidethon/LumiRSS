/** NEW-261 术语表冲突处理 — 同词多义冲突清单：变体的来源与适用范围可见，
 * 用户为当前来源（scope=source，绑定 feed_url）或项目登记生效译法。
 * 写入推进 glossary_version：已产生译文缓存原样，其后新生成按生效译法。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  clearGlossaryChoice,
  listGlossaryConflicts,
  setGlossaryChoice,
  type GlossaryConflict,
} from '../../api/new261'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { NoticeLine } from './parts'

const SOURCE_URL_MAX = 2048

export function GlossaryConflictsPanel() {
  const queryClient = useQueryClient()
  const conflictsQuery = useQuery({
    queryKey: ['new261-glossary-conflicts'],
    queryFn: ({ signal }) => listGlossaryConflicts(signal),
  })
  const [notice, setNotice] = useState<string | null>(null)

  const chooseMutation = useMutation({
    mutationFn: (input: { conflict: GlossaryConflict; termId: string; scope: 'project' | 'source'; sourceUrl: string }) =>
      setGlossaryChoice(input.conflict.term, input.termId, input.scope, input.sourceUrl),
    onSuccess: (choice) => {
      setNotice(`已为${choice.scope === 'source' ? '当前来源' : '项目'}登记生效译法；其后新生成的翻译按此出稿。`)
      void queryClient.invalidateQueries({ queryKey: ['new261-glossary-conflicts'] })
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '登记失败'),
  })
  const clearMutation = useMutation({
    mutationFn: (input: { term: string; scope: 'project' | 'source'; sourceUrl: string }) =>
      clearGlossaryChoice(input.term, input.scope, input.sourceUrl),
    onSuccess: () => {
      setNotice('已清除该选择，回到默认解析。')
      void queryClient.invalidateQueries({ queryKey: ['new261-glossary-conflicts'] })
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '清除失败'),
  })

  const conflicts = conflictsQuery.data?.conflicts ?? []

  return (
    <div className="flex flex-col gap-2">
      {conflictsQuery.isPending && <p className="text-xs text-[var(--lumi-text-tertiary)]">载入冲突清单…</p>}
      {conflictsQuery.isError && (
        <NoticeLine tone="error">术语冲突清单载入失败：{String(conflictsQuery.error)}</NoticeLine>
      )}
      {conflictsQuery.isSuccess && conflicts.length === 0 && (
        <EmptyState title="没有同名多义冲突" description="术语表当前没有同一词存在不同译法的冲突组。" />
      )}
      {conflicts.map((conflict) => (
        <ConflictGroup
          key={conflict.term}
          conflict={conflict}
          busy={chooseMutation.isPending || clearMutation.isPending}
          onChoose={(termId, scope, sourceUrl) => chooseMutation.mutate({ conflict, termId, scope, sourceUrl })}
          onClear={(scope, sourceUrl) => clearMutation.mutate({ term: conflict.term, scope, sourceUrl })}
        />
      ))}
      {notice !== null && <NoticeLine tone={notice.includes('失败') ? 'error' : 'success'}>{notice}</NoticeLine>}
    </div>
  )
}

function ConflictGroup({
  conflict,
  busy,
  onChoose,
  onClear,
}: {
  conflict: GlossaryConflict
  busy: boolean
  onChoose: (termId: string, scope: 'project' | 'source', sourceUrl: string) => void
  onClear: (scope: 'project' | 'source', sourceUrl: string) => void
}) {
  const [selected, setSelected] = useState<string>(conflict.variants[0]?.termId ?? '')
  const [scope, setScope] = useState<'project' | 'source'>('project')
  const [sourceUrl, setSourceUrl] = useState('')

  return (
    <div
      aria-label={`术语冲突：${conflict.term}`}
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2"
    >
      <p className="text-sm font-medium text-[var(--lumi-text-primary)]">
        {conflict.term}
        <span className="ml-2 text-xs text-[var(--lumi-text-tertiary)]">
          {conflict.variants.length} 种译法
        </span>
      </p>
      <ul className="flex flex-col gap-1">
        {conflict.variants.map((variant) => (
          <li key={variant.termId} className="flex items-start gap-2 text-xs text-[var(--lumi-text-secondary)]">
            <label className="flex items-start gap-1.5">
              <input
                type="radio"
                name={`new261-term-${conflict.term}`}
                checked={selected === variant.termId}
                onChange={() => setSelected(variant.termId)}
                aria-label={`选择译法：${variant.definition}`}
                className="mt-0.5 size-3.5"
              />
              <span>
                {variant.definition}
                <span className="ml-1 text-[var(--lumi-text-tertiary)]">
                  （来源 {variant.sourceRef || '全局'} · 更新 {variant.updatedAt || '—'}）
                </span>
              </span>
            </label>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-xs text-[var(--lumi-text-secondary)]">
          生效范围
          <select
            value={scope}
            onChange={(event) => setScope(event.target.value === 'source' ? 'source' : 'project')}
            aria-label={`生效范围：${conflict.term}`}
            className="ml-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5 py-1 text-xs"
          >
            <option value="project">项目（全部来源）</option>
            <option value="source">当前来源</option>
          </select>
        </label>
        {scope === 'source' && (
          <input
            type="url"
            value={sourceUrl}
            maxLength={SOURCE_URL_MAX}
            onChange={(event) => setSourceUrl(event.target.value)}
            placeholder="来源 feed 地址"
            aria-label={`来源地址：${conflict.term}`}
            className="min-w-48 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
          />
        )}
        <Button
          size="sm"
          variant="secondary"
          disabled={busy || selected === ''}
          onClick={() => onChoose(selected, scope, sourceUrl.trim())}
        >
          设为生效译法
        </Button>
      </div>
      {conflict.chosen && (
        <p className="flex flex-wrap items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
          当前生效：{conflict.chosen.scope === 'source' ? '来源' : '项目'}选择 ·{' '}
          {conflict.variants.find((v) => v.termId === conflict.chosen?.chosenTermId)?.definition ??
            conflict.chosen.chosenTermId}
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => onClear(conflict.chosen!.scope, conflict.chosen!.sourceUrl)}
          >
            清除此选择
          </Button>
        </p>
      )}
    </div>
  )
}
