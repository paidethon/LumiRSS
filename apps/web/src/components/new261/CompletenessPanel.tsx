/** NEW-270 翻译完整性报告 — 任务结束按原文段落分类：完成 / 缺失 /
 * 失败（无法翻译）/ 跳过；用户显式「补译缺段」只发 missing+failed 段
 * （其余段零 provider 调用），不是只看成功百分比。快照历史可回看。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  buildCompletenessReport,
  fillCompleteness,
  listCompletenessReports,
  type CompletenessReport,
} from '../../api/new261'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { IndexBadges, NoticeLine } from './parts'

export function CompletenessPanel({
  entryRef,
  blocks,
}: {
  entryRef: string
  blocks: Array<{ index: number; text: string }> | null
}) {
  const queryClient = useQueryClient()
  const historyQuery = useQuery({
    queryKey: ['new270-completeness-reports', entryRef],
    queryFn: ({ signal }) => listCompletenessReports(entryRef, signal),
  })
  const [report, setReport] = useState<CompletenessReport | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const reportMutation = useMutation({
    mutationFn: () => buildCompletenessReport(entryRef, blocks ?? []),
    onSuccess: (result) => {
      setReport(result)
      setNotice(null)
      void queryClient.invalidateQueries({ queryKey: ['new270-completeness-reports', entryRef] })
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '报告失败'),
  })
  const fillMutation = useMutation({
    mutationFn: () => fillCompleteness(entryRef, blocks ?? []),
    onSuccess: (result) => {
      setReport(result)
      setNotice(`补译完成：本次补成功 ${result.filled} 段（只发送缺失/失败段）。`)
      void queryClient.invalidateQueries({ queryKey: ['new270-completeness-reports', entryRef] })
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '补译失败'),
  })

  const gap = report !== null ? report.missing + report.failed : 0
  const history = historyQuery.data?.reports ?? []

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          disabled={blocks === null || blocks.length === 0 || reportMutation.isPending}
          onClick={() => reportMutation.mutate()}
        >
          生成完整性报告
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={blocks === null || blocks.length === 0 || fillMutation.isPending}
          onClick={() => fillMutation.mutate()}
        >
          补译缺失段{report !== null && gap > 0 ? `（${gap} 段）` : ''}
        </Button>
      </div>

      {report !== null && (
        <div className="flex flex-col gap-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          <p>
            共 {report.total} 段：完成 {report.translated} · 缺失 {report.missing} · 失败 {report.failed} ·
            跳过（不翻译）{report.skipped}
          </p>
          {report.translatedIndexes.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span>完成：</span>
              <IndexBadges indexes={report.translatedIndexes} />
            </div>
          )}
          {report.missingIndexes.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span>缺失：</span>
              <IndexBadges indexes={report.missingIndexes} />
            </div>
          )}
          {report.failedIndexes.length > 0 && (
            <div className="flex flex-wrap items-center gap-1 text-[var(--lumi-danger)]">
              <span>无法翻译（失败）：</span>
              <IndexBadges indexes={report.failedIndexes} />
            </div>
          )}
          {report.skippedIndexes.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span>跳过：</span>
              <IndexBadges indexes={report.skippedIndexes} />
            </div>
          )}
        </div>
      )}

      {history.length > 0 && (
        <details className="text-xs text-[var(--lumi-text-secondary)]">
          <summary className="cursor-pointer">快照历史（{history.length} 份）</summary>
          <ul className="mt-1 flex flex-col gap-1">
            {history.map((item) => (
              <li key={item.id} className="rounded-[var(--lumi-radius-sm)] bg-[var(--lumi-surface-hover)] p-1.5">
                {item.createdAt} · 完成 {item.translated}/{item.total} · 缺 {item.missing} · 败 {item.failed}
                {item.filled > 0 ? ` · 补成功 ${item.filled}` : ''}
              </li>
            ))}
          </ul>
        </details>
      )}

      {blocks === null && <EmptyState title="还没有正文块" description="切到双语/仅译文并等正文分段后再生成报告。" />}
      {notice !== null && <NoticeLine tone={notice.includes('失败') ? 'error' : 'success'}>{notice}</NoticeLine>}
    </div>
  )
}
