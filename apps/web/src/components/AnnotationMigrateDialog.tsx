/** AnnotationMigrateDialog — N078 批注跨版本迁移（逐项确认）。
 *
 * 选文章（来自既有批注的 entryRef）+ 版本方向（current ↔
 * last_known_full）→ 预览：候选匹配（N071 同口径打分，逐条勾选）+
 * 未能匹配的诚实列表（no_quote/no_match）→ 应用所选（走与 N071
 * repair 相同的 rebind：旧锚点进修复历史，可循历史撤销）。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { migrateAnnotationsApply, migrateAnnotationsPreview } from '../api/client'
import type {
  Annotation,
  AnnotationMigrateApplyResult,
  AnnotationMigrateCandidate,
  AnnotationVersionKey,
} from '../api/client'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { EmptyState } from './ui/EmptyState'

const VERSION_LABELS: Record<AnnotationVersionKey, string> = {
  current: '上游当前',
  last_known_full: '上次完整版本',
}

export function AnnotationMigrateDialog({
  annotations,
  onClose,
}: {
  annotations: Annotation[]
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const entryRefs = useMemo(
    () => [...new Set(annotations.map((a) => a.entryRef))],
    [annotations],
  )
  const [entryRef, setEntryRef] = useState(entryRefs[0] ?? '')
  const [fromVersion, setFromVersion] = useState<AnnotationVersionKey>('current')
  const [toVersion, setToVersion] = useState<AnnotationVersionKey>('last_known_full')
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [result, setResult] = useState<AnnotationMigrateApplyResult | null>(null)

  const previewQuery = useQuery({
    queryKey: ['annotation-migrate-preview', entryRef, fromVersion, toVersion],
    queryFn: () => migrateAnnotationsPreview({ entryRef, fromVersion, toVersion }),
    enabled: entryRef !== '',
  })
  const matched = previewQuery.data?.matched ?? []
  const unmatched = previewQuery.data?.unmatched ?? []

  const applyMutation = useMutation({
    mutationFn: () =>
      migrateAnnotationsApply({
        entryRef,
        fromVersion,
        toVersion,
        items: matched
          .filter((candidate: AnnotationMigrateCandidate) => checked.has(candidate.annotationId))
          .map((candidate) => ({
            annotationId: candidate.annotationId,
            blockIndex: candidate.candidateBlockIndex,
          })),
      }),
    onSuccess: async (result) => {
      setResult(result)
      await queryClient.invalidateQueries({ queryKey: ['annotations-manager'] })
      await queryClient.invalidateQueries({ queryKey: ['annotation-migrate-preview'] })
    },
  })

  const toggle = (id: string) => {
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const reasonText = (reason: string | null) =>
    reason === 'target_conflict'
      ? '目标位置已有其他批注（跳过，不覆盖）'
      : reason === 'low_score'
        ? '所选块相似度过低'
        : reason === 'not_found'
          ? '批注不存在'
          : reason === 'block_out_of_range'
            ? '目标块超出范围'
            : reason ?? '失败'

  return (
    <Dialog open onClose={onClose} title="批注跨版本迁移" panelClassName="max-w-xl">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
          <label className="flex items-center gap-1.5">
            文章
            <select
              aria-label="选择文章"
              value={entryRef}
              onChange={(e) => {
                setEntryRef(e.target.value)
                setChecked(new Set())
                setResult(null)
              }}
              className="max-w-56 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
            >
              {entryRefs.map((ref) => (
                <option key={ref} value={ref}>{ref.slice(0, 24)}…</option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1.5">
            从
            <select
              aria-label="来源版本"
              value={fromVersion}
              onChange={(e) => {
                setFromVersion(e.target.value as AnnotationVersionKey)
                setChecked(new Set())
                setResult(null)
              }}
              className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
            >
              <option value="current">{VERSION_LABELS.current}</option>
              <option value="last_known_full">{VERSION_LABELS.last_known_full}</option>
            </select>
          </label>
          <label className="flex items-center gap-1.5">
            到
            <select
              aria-label="目标版本"
              value={toVersion}
              onChange={(e) => {
                setToVersion(e.target.value as AnnotationVersionKey)
                setChecked(new Set())
                setResult(null)
              }}
              className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
            >
              <option value="current">{VERSION_LABELS.current}</option>
              <option value="last_known_full">{VERSION_LABELS.last_known_full}</option>
            </select>
          </label>
        </div>

        {entryRef !== '' && fromVersion === toVersion && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">来源与目标版本不能相同。</p>
        )}

        {entryRef !== '' && fromVersion !== toVersion && (
          <>
            {previewQuery.isPending && <p className="text-xs text-[var(--lumi-text-tertiary)]">正在生成迁移预览…</p>}
            {previewQuery.isError && (
              <p role="alert" className="text-xs text-[var(--lumi-danger)]">
                预览失败：{previewQuery.error instanceof Error ? previewQuery.error.message : '目标版本可能不可用'}
              </p>
            )}
            {previewQuery.isSuccess && matched.length === 0 && unmatched.length === 0 && (
              <EmptyState title="这篇文章没有批注" />
            )}
            {matched.length > 0 && (
              <ul className="flex flex-col gap-1.5">
                {matched.map((candidate) => (
                  <li
                    key={candidate.annotationId}
                    className="flex items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1.5 text-xs"
                  >
                    <input
                      type="checkbox"
                      checked={checked.has(candidate.annotationId)}
                      onChange={() => toggle(candidate.annotationId)}
                      aria-label={`确认迁移批注 ${candidate.annotationId}`}
                      className="size-3.5"
                    />
                    <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-secondary)]">
                      {candidate.excerpt}
                    </span>
                    <span className="text-[var(--lumi-text-tertiary)]">
                      块 {candidate.candidateBlockIndex} · 相似度 {candidate.score.toFixed(2)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {unmatched.length > 0 && (
              <p className="text-xs text-[var(--lumi-text-tertiary)]">
                {unmatched.length} 条批注未找到候选
                （{unmatched.map((u) => (u.reason === 'no_quote' ? '无引文' : '目标版本中无匹配')).join('、')}）——
                保持原样，不假装迁移。
              </p>
            )}
            {result !== null && (
              <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
                已迁移 {result.applied.length} 条
                {result.failed.length > 0 &&
                  `；${result.failed.length} 条失败（${result.failed.map((f) => reasonText(f.reason)).join('；')}）`}
                。误迁移可从批注修复历史撤销。
              </p>
            )}
            <div className="flex items-center justify-end gap-2">
              <Button size="sm" variant="ghost" onClick={onClose}>关闭</Button>
              <Button
                size="sm"
                variant="primary"
                disabled={checked.size === 0 || applyMutation.isPending}
                onClick={() => applyMutation.mutate()}
              >
                迁移所选（{checked.size}）
              </Button>
            </div>
          </>
        )}
      </div>
    </Dialog>
  )
}
