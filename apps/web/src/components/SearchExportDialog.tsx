/** SearchExportDialog — F073 引用清单导出（SearchPage）。
 *
 * 范围预览（真实总数，dryRun）→ 格式选择 + 摘录字段勾选 → 执行下载；
 * 超 cap 截断诚实标注（X-Lumi-Truncated）。 */

import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import { exportSearchList } from '../api/client'
import { Dialog } from './ui/Dialog'
import { Button } from './ui/Button'
import { Switch } from './ui/Switch'

export function SearchExportDialog({
  open,
  onClose,
  query,
}: {
  open: boolean
  onClose: () => void
  query: string
}) {
  const [format, setFormat] = useState<'csv' | 'markdown'>('csv')
  const [includeExcerpt, setIncludeExcerpt] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => {
    if (open) setNote(null)
  }, [open])

  const run = useMutation({
    mutationFn: async (dryRun: boolean) => {
      if (dryRun) {
        const response = await fetch(`${import.meta.env.BASE_URL ?? ''}api/v1/search/export`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ q: query, dryRun: true }),
        })
        if (!response.ok) throw new Error('预览失败')
        return (await response.json()) as { total: number; capped: boolean }
      }
      const result = await exportSearchList({ q: query, format, includeExcerpt })
      // 下载
      const blob = new Blob([result.content], { type: result.contentType })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `lumi-search.${format === 'csv' ? 'csv' : 'md'}`
      document.body.append(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
      return { total: result.total, capped: result.truncated }
    },
    onSuccess: (result, dryRun) => {
      if (dryRun) {
        setNote(`当前范围命中 ${result.total} 条${result.capped ? '（超过上限，将截断）' : ''}。`)
        return
      }
      setNote(
        result.capped
          ? `已导出 ${result.total} 条（命中超过上限，已截断标注）。`
          : `已导出 ${result.total} 条，未截断。`,
      )
    },
  })

  return (
    <Dialog open={open} onClose={onClose} title="导出清单" panelClassName="max-w-md">
      <div className="flex flex-col gap-3" data-lumi-search-export="">
        <p className="text-xs text-[var(--lumi-text-secondary)]">
          导出当前搜索「{query}」的引用清单（标题/来源/日期/链接，
          摘录 ≤200 字——绝不含正文全文；上限 2000 条，超限截断标注）。
        </p>
        <label className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
          格式
          <select
            aria-label="导出格式"
            value={format}
            onChange={(e) => setFormat(e.target.value as 'csv' | 'markdown')}
            className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 text-sm"
          >
            <option value="csv">CSV（表格软件）</option>
            <option value="markdown">Markdown</option>
          </select>
        </label>
        <Switch
          checked={includeExcerpt}
          onCheckedChange={setIncludeExcerpt}
          label="包含摘录列（≤200 字）"
        />
        <div className="flex items-center justify-end gap-2">
          <Button size="sm" variant="ghost" disabled={run.isPending} onClick={() => run.mutate(true)}>
            {run.isPending ? '统计中…' : '预览总数'}
          </Button>
          <Button
            size="sm"
            variant="primary"
            disabled={run.isPending || query.trim() === ''}
            onClick={() => run.mutate(false)}
          >
            <Download aria-hidden className="size-3.5" />
            {run.isPending ? '导出中…' : '导出'}
          </Button>
        </div>
        {note !== null && (
          <p role="status" className="text-xs text-[var(--lumi-text-secondary)]" aria-live="polite">
            {note}
          </p>
        )}
        {run.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            导出失败，请稍后重试。
          </p>
        )}
      </div>
    </Dialog>
  )
}
