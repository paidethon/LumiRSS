/** NEW-244 链接存活复核 — 一批资料（每行一个 ref）后台有界检查原文可达性，
 * 四档结果：正常 / 重定向 / 失效 / 无法判断（无法判断绝不冒充失效）。 */

import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { listLinkRecheckResults, runLinkRecheck, type LinkRecheckItem } from '../../api/new241'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/Skeleton'

const STATUS_LABELS: Record<LinkRecheckItem['status'], string> = {
  ok: '正常',
  redirect: '重定向',
  dead: '失效',
  unknown: '无法判断',
}

export function LinkRecheckPanel({ entryRef }: { entryRef: string }) {
  const [refsText, setRefsText] = useState(entryRef)
  const [notice, setNotice] = useState<string | null>(null)

  const results = useQuery({
    queryKey: ['new244-link-recheck-results'],
    queryFn: ({ signal }) => listLinkRecheckResults(signal),
  })

  const runMutation = useMutation({
    mutationFn: () =>
      runLinkRecheck(
        refsText
          .split('\n')
          .map((line) => line.trim())
          .filter((line) => line !== ''),
      ),
    onSuccess: (result) => setNotice(`本轮检查完成：${result.count} 条结果已入台账。`),
    onError: (error) => setNotice(error instanceof Error ? error.message : '检查失败'),
  })

  return (
    <section
      aria-label="链接存活复核（NEW-244）"
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
    >
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">链接存活复核</h3>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">NEW-244</span>
      </div>

      <textarea
        aria-label="资料引用列表（每行一个）"
        value={refsText}
        onChange={(event) => setRefsText(event.target.value)}
        placeholder="每行一个资料 ref（最多 50 条）"
        rows={3}
        className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
      />
      <Button
        size="sm"
        variant="secondary"
        className="self-start"
        disabled={refsText.trim() === '' || runMutation.isPending}
        onClick={() => runMutation.mutate()}
      >
        {runMutation.isPending ? '检查中…' : '开始复核'}
      </Button>

      {runMutation.data && (
        <ul className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]" aria-label="本轮复核结果">
          {runMutation.data.items.map((item) => (
            <li key={item.id}>
              <span className="text-[var(--lumi-text-primary)]">{item.ref}</span> —{' '}
              {STATUS_LABELS[item.status]}
              {item.httpStatus !== null ? `（HTTP ${item.httpStatus}）` : ''}
              {item.status === 'redirect' && item.finalUrl !== null ? ` → ${item.finalUrl}` : ''}
              {item.detail !== '' ? `；${item.detail}` : ''}
            </li>
          ))}
        </ul>
      )}

      {results.isPending && <Skeleton className="h-8 w-full" />}
      {results.isError && (
        <div role="alert" className="text-xs text-[var(--lumi-text-secondary)]">
          台账加载失败。{results.error instanceof Error ? results.error.message : ''}
        </div>
      )}
      {results.data && results.data.items.length > 0 && (
        <details className="text-xs text-[var(--lumi-text-secondary)]">
          <summary className="cursor-pointer">历史台账（{results.data.items.length} 条）</summary>
          <ul className="mt-1 flex flex-col gap-1">
            {results.data.items.map((item) => (
              <li key={`ledger-${item.id}`}>
                {item.ref} — {STATUS_LABELS[item.status]}
                {item.httpStatus !== null ? `（HTTP ${item.httpStatus}）` : ''}
              </li>
            ))}
          </ul>
        </details>
      )}

      {notice !== null && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
          {notice}
        </p>
      )}
    </section>
  )
}
