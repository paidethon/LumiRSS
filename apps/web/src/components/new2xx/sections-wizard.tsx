/** NEW-225 积压处理向导 section —— 抽样预览 → keep / 归档(两段式) / 分批。
 *
 * 归档必须先「预演」拿到 token 再显式确认；绝不默认全标已读。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import {
  listQueueSlots,
  wizardArchiveApply,
  wizardArchivePreview,
  wizardKeep,
  wizardPreview,
  wizardStage,
  type WizardGroup,
} from './api'
import { Button } from '../ui/Button'
import { Chip, ErrorNote, SectionShell } from './parts'

const DAY_OPTIONS = [7, 30, 90, 365]

interface ArchiveDraft {
  feedUrl: string
  count: number
  token: string
}

export function WizardSection() {
  const qc = useQueryClient()
  const [days, setDays] = useState(30)
  const [groups, setGroups] = useState<WizardGroup[]>([])
  const [keptExcluded, setKeptExcluded] = useState(0)
  const [archiveDrafts, setArchiveDrafts] = useState<Record<string, ArchiveDraft>>({})
  const [applied, setApplied] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)

  const slotsQuery = useQuery({
    queryKey: ['new2xx', 'slots'],
    queryFn: ({ signal }) => listQueueSlots(signal),
  })
  const slots = slotsQuery.data?.slots ?? []

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['new2xx', 'slots'] })
  }

  const previewMutation = useMutation({
    mutationFn: () => wizardPreview(days),
    onSuccess: (view) => {
      setGroups(view.groups)
      setKeptExcluded(view.keptDecisionsExcluded)
      setArchiveDrafts({})
      setApplied(null)
      setError(null)
    },
    onError: setError,
  })
  const keepMutation = useMutation({
    mutationFn: (feedUrl: string) => wizardKeep(feedUrl, days),
    onSuccess: () => previewMutation.mutate(),
    onError: setError,
  })
  const archivePreviewMutation = useMutation({
    mutationFn: (feedUrl: string) => wizardArchivePreview(feedUrl, days),
    onSuccess: (view, feedUrl) => {
      setArchiveDrafts((prev) => ({
        ...prev,
        [feedUrl]: { feedUrl, count: view.count, token: view.confirmToken },
      }))
    },
    onError: setError,
  })
  const archiveApplyMutation = useMutation({
    mutationFn: (draft: ArchiveDraft) =>
      wizardArchiveApply(draft.feedUrl, days, draft.token),
    onSuccess: (result) => {
      setApplied(`已归档 ${result.applied} 篇${result.failed ? `（${result.failed} 篇失败）` : ''}`)
      previewMutation.mutate()
    },
    onError: setError,
  })
  const stageMutation = useMutation({
    mutationFn: ({ feedUrl, slotId }: { feedUrl: string; slotId: string }) =>
      wizardStage(feedUrl, days, slotId),
    onSuccess: invalidate,
    onError: setError,
  })

  return (
    <SectionShell
      title="积压处理向导"
      hint="选范围 → 按来源抽样预览 → 逐来源决定：保留 / 分批读 / 归档。归档需要两步确认，绝不默认全标已读。"
    >
      <ErrorNote error={error} />
      <div className="flex items-center gap-2 text-xs">
        <label className="flex items-center gap-1.5 text-[var(--lumi-text-secondary)]">
          超过
          <select
            value={days}
            onChange={(event) => setDays(Number(event.target.value))}
            className="min-h-7 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-separator)] bg-[var(--lumi-surface-elevated)] px-1 text-xs"
          >
            {DAY_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option} 天
              </option>
            ))}
          </select>
          未读
        </label>
        <Button size="sm" disabled={previewMutation.isPending} onClick={() => previewMutation.mutate()}>
          预览
        </Button>
        {keptExcluded > 0 ? <Chip>已排除 {keptExcluded} 个「审过保留」的来源</Chip> : null}
      </div>
      {applied ? (
        <p role="status" className="text-xs text-[var(--lumi-success)]">
          {applied}
        </p>
      ) : null}

      {groups.length === 0 ? (
        <p className="text-xs text-[var(--lumi-text-tertiary)]">
          还没有预览。选好范围点「预览」——预览是纯读取，不做任何改动。
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {groups.map((group) => {
            const draft = archiveDrafts[group.feedUrl]
            return (
              <li
                key={group.feedUrl}
                className="flex flex-col gap-1.5 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-separator)] p-2 text-xs"
              >
                <div className="flex items-center gap-2">
                  <span className="font-medium text-[var(--lumi-text-primary)]">
                    {group.feedTitle ?? group.feedUrl}
                  </span>
                  <Chip tone="warn">{group.unreadCount} 篇未读</Chip>
                </div>
                {group.sample.length > 0 ? (
                  <p className="truncate text-[var(--lumi-text-tertiary)]">
                    样本：{group.sample.map((entry) => entry.title).join(' / ')}
                  </p>
                ) : null}
                <div className="flex flex-wrap items-center gap-1.5">
                  <Button size="sm" variant="ghost" onClick={() => keepMutation.mutate(group.feedUrl)}>
                    保留未读
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={slots.length === 0 || stageMutation.isPending}
                    onClick={() => {
                      const slotId = slots[0]?.id
                      if (slotId) stageMutation.mutate({ feedUrl: group.feedUrl, slotId })
                    }}
                  >
                    加入第一个时段分批读
                  </Button>
                  {!draft ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => archivePreviewMutation.mutate(group.feedUrl)}
                    >
                      归档（先预演）
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant="danger"
                      disabled={archiveApplyMutation.isPending}
                      onClick={() => archiveApplyMutation.mutate(draft)}
                    >
                      确认归档这 {draft.count} 篇（置读）
                    </Button>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </SectionShell>
  )
}
