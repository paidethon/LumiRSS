/** NEW-250 证据完整性检查单 — 为一份个人报告检查每条引文是否具备
 * 来源 / 保存版本 / 可定位片段；缺项逐个补齐（版本以 NEW-241 保存为准）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { createEvidenceChecklist, getEvidenceChecklist, patchEvidenceItem, type EvidenceItemView } from '../../api/new241'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'

function MissingBadges({ item }: { item: EvidenceItemView }) {
  return (
    <span>
      来源：{item.hasSource ? '有' : '缺'}；保存版本：
      {item.hasVersion ? (item.versionExists === false ? '有（但版本已删除）' : '有') : '缺'}；片段：
      {item.hasExcerpt ? '有' : '缺'}
    </span>
  )
}

export function EvidenceChecklistPanel() {
  const queryClient = useQueryClient()
  const [reportLabel, setReportLabel] = useState('')
  const [refsText, setRefsText] = useState('')
  const [openLabel, setOpenLabel] = useState('')
  const [targetItem, setTargetItem] = useState('')
  const [sourceRef, setSourceRef] = useState('')
  const [versionId, setVersionId] = useState('')
  const [excerpt, setExcerpt] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const checklist = useQuery({
    queryKey: ['new250-evidence-checklist', openLabel],
    queryFn: ({ signal }) => getEvidenceChecklist(openLabel, signal),
    enabled: openLabel !== '',
  })

  const createMutation = useMutation({
    mutationFn: (input: { label: string; refs: string[] }) =>
      createEvidenceChecklist(input.label, input.refs),
    onSuccess: async (_result, input) => {
      setNotice('检查单已建立。')
      setOpenLabel(input.label)
      await queryClient.invalidateQueries({ queryKey: ['new250-evidence-checklist', input.label] })
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '建单失败'),
  })

  const patchMutation = useMutation({
    mutationFn: () => {
      const patch: { sourceRef?: string; versionId?: string; excerpt?: string } = {}
      if (sourceRef.trim() !== '') patch.sourceRef = sourceRef
      if (versionId.trim() !== '') patch.versionId = versionId
      if (excerpt.trim() !== '') patch.excerpt = excerpt
      return patchEvidenceItem(openLabel, targetItem, patch)
    },
    onSuccess: async () => {
      setNotice('缺项已补齐。')
      setSourceRef('')
      setVersionId('')
      setExcerpt('')
      await queryClient.invalidateQueries({ queryKey: ['new250-evidence-checklist', openLabel] })
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '补齐失败'),
  })

  const items = checklist.data?.items ?? []
  const selected = items.find((item) => item.citationRef === targetItem) ?? null

  return (
    <section
      aria-label="证据完整性检查单（NEW-250）"
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
    >
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">证据完整性检查单</h3>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">NEW-250</span>
      </div>

      <div className="flex flex-col gap-1">
        <input
          aria-label="报告名称"
          value={reportLabel}
          onChange={(event) => setReportLabel(event.target.value)}
          placeholder="例如：九月综述"
          className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
        />
        <textarea
          aria-label="报告引文 ref 列表（每行一个）"
          value={refsText}
          onChange={(event) => setRefsText(event.target.value)}
          placeholder="每行一条引文 ref"
          rows={3}
          className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
        />
        <Button
          size="sm"
          variant="secondary"
          className="self-start"
          disabled={reportLabel.trim() === '' || refsText.trim() === '' || createMutation.isPending}
          onClick={() =>
            createMutation.mutate({
              label: reportLabel,
              refs: refsText
                .split('\n')
                .map((line) => line.trim())
                .filter((line) => line !== ''),
            })
          }
        >
          建立检查单
        </Button>
      </div>

      {openLabel !== '' && checklist.isPending && <Skeleton className="h-12 w-full" />}
      {openLabel !== '' && checklist.isError && (
        <div role="alert" className="text-xs text-[var(--lumi-text-secondary)]">
          检查单加载失败。{checklist.error instanceof Error ? checklist.error.message : ''}
        </div>
      )}
      {checklist.data && (
        <div className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
          <p>
            「{checklist.data.reportLabel}」共 {checklist.data.total} 条：完整{' '}
            {checklist.data.completeCount} / 缺项 {checklist.data.missingCount}。
          </p>
          <ul className="flex flex-col gap-1">
            {items.map((item) => (
              <li key={item.citationRef} className="flex flex-col gap-0.5">
                <span className={item.complete ? '' : 'text-[var(--lumi-text-primary)]'}>
                  {item.complete ? '✓' : '✗'} {item.citationRef}
                </span>
                {!item.complete && (
                  <>
                    <MissingBadges item={item} />
                    {item.missing.length > 0 && <span>缺：{item.missing.join('、')}</span>}
                  </>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {items.length > 0 && (
        <div className="flex flex-col gap-1 border-t border-[var(--lumi-border)] pt-2">
          <label className="text-xs text-[var(--lumi-text-secondary)]">
            补齐目标
            <select
              aria-label="选择要补齐的引文项"
              value={targetItem}
              onChange={(event) => setTargetItem(event.target.value)}
              className="ml-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1"
            >
              <option value="">选择引文项…</option>
              {items.map((item) => (
                <option key={item.citationRef} value={item.citationRef}>
                  {item.citationRef}
                </option>
              ))}
            </select>
          </label>
          {selected !== null && (
            <p className="text-xs text-[var(--lumi-text-tertiary)]">
              当前缺：{selected.missing.length > 0 ? selected.missing.join('、') : '无（已完整）'}
            </p>
          )}
          <input
            aria-label="补齐来源 ref"
            value={sourceRef}
            onChange={(event) => setSourceRef(event.target.value)}
            placeholder="来源 ref（留空不动）"
            className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
          />
          <input
            aria-label="补齐保存版本 id"
            value={versionId}
            onChange={(event) => setVersionId(event.target.value)}
            placeholder="保存版本 id（NEW-241 保存的版本；留空不动）"
            className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
          />
          <textarea
            aria-label="补齐可定位片段"
            value={excerpt}
            onChange={(event) => setExcerpt(event.target.value)}
            placeholder="可定位片段（留空不动）"
            rows={2}
            className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
          />
          <Button
            size="sm"
            variant="secondary"
            className="self-start"
            disabled={targetItem === '' || patchMutation.isPending}
            onClick={() => patchMutation.mutate()}
          >
            保存补齐
          </Button>
        </div>
      )}

      {openLabel !== '' && checklist.data !== undefined && items.length === 0 && (
        <EmptyState title="这个报告没有检查项" description="建单时至少要给一条引文 ref。" />
      )}

      {notice !== null && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
          {notice}
        </p>
      )}
    </section>
  )
}
