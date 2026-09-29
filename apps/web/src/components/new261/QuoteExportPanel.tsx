/** NEW-268 译文引用导出 — 导出一段人工确认的译文时同时附原文、来源与
 * 机器/人工标记：必须显式勾选「确认」才可导出；渲染文本（含出处行）
 * 可复制；台账按篇回看（不含渲染文本）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { TranslationSegmentState } from '../../api/types'
import { exportQuote, listQuoteExports } from '../../api/new261'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { NoticeLine } from './parts'

export function QuoteExportPanel({
  entryRef,
  segments,
  blockTexts,
}: {
  entryRef: string
  segments: TranslationSegmentState[]
  /** 块索引 → 源文本（POST body 需要 blockText；由持有 blocks 的容器提供）。 */
  blockTexts: Map<number, string>
}) {
  const queryClient = useQueryClient()
  const ledgerQuery = useQuery({
    queryKey: ['new268-quote-exports', entryRef],
    queryFn: ({ signal }) => listQuoteExports(entryRef, signal),
  })
  const exported = segments.filter(
    (segment) => segment.status === 'success' && (segment.userRevision || segment.translatedText),
  )
  const [blockIndex, setBlockIndex] = useState<number>(exported[0]?.index ?? -1)
  const [confirmed, setConfirmed] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const exportMutation = useMutation({
    mutationFn: () =>
      exportQuote(entryRef, blockIndex, blockTexts.get(blockIndex) ?? '', confirmed),
    onSuccess: (result) => {
      setNotice(`已导出第 ${result.blockIndex + 1} 段（${result.humanRevised ? '人工修订' : '机器译文'}）。`)
      setConfirmed(false)
      void queryClient.invalidateQueries({ queryKey: ['new268-quote-exports', entryRef] })
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '导出失败'),
  })

  const selectedSegment = segments.find((item) => item.index === blockIndex)
  const isHuman = selectedSegment?.userRevision != null && selectedSegment.userRevision !== ''
  const ledger = ledgerQuery.data?.exports ?? []

  return (
    <div className="flex flex-col gap-2">
      {exported.length === 0 ? (
        <EmptyState title="没有可导出的译文段" description="完成一次翻译（或修订）后，这里按段导出引用。" />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-xs text-[var(--lumi-text-secondary)]">
              导出段落
              <select
                value={blockIndex}
                onChange={(event) => setBlockIndex(Number(event.target.value))}
                aria-label="导出的段落"
                className="ml-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5 py-1 text-xs"
              >
                {exported.map((segment) => (
                  <option key={segment.index} value={segment.index}>
                    第 {segment.index + 1} 段{segment.userRevision ? '（人工修订）' : ''}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
                aria-label="确认此译文可引用"
                className="size-3.5"
              />
              我确认此译文可引用
            </label>
            <Button
              size="sm"
              variant="secondary"
              disabled={!confirmed || blockIndex < 0 || exportMutation.isPending}
              onClick={() => exportMutation.mutate()}
            >
              确认并导出
            </Button>
          </div>
          <p className="text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
            导出将附：原文、来源（feed / 链接）与「{isHuman ? '人工修订' : '机器译文'}」标记 —— 不确认不导出。
          </p>
        </>
      )}

      {ledger.length > 0 && (
        <details className="text-xs text-[var(--lumi-text-secondary)]">
          <summary className="cursor-pointer">导出台账（{ledger.length} 条）</summary>
          <ul className="mt-1 flex flex-col gap-1">
            {ledger.map((item) => (
              <li key={item.id} className="rounded-[var(--lumi-radius-sm)] bg-[var(--lumi-surface-hover)] p-1.5">
                第 {item.blockIndex + 1} 段 · {item.humanRevised ? '人工修订' : '机器译文'} · {item.feedTitle || item.sourceUrl || '来源未知'} ·{' '}
                {item.createdAt}
              </li>
            ))}
          </ul>
        </details>
      )}
      {notice !== null && <NoticeLine tone={notice.includes('失败') ? 'error' : 'success'}>{notice}</NoticeLine>}
    </div>
  )
}
