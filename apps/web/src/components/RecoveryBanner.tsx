/** N037 断更恢复横幅（EntryList 工具区）。
 *
 * 来源从 error/stale 恢复为 ok 时，服务端自动记录恢复窗口（含窗口内
 * 条目引用 ≤50）；本横幅列出**待处理**窗口，一键「加入补读队列」：
 * - 一次性消费（重复 → 409 recovery_already_consumed，UI 提示已加入）；
 * - 入队走既有队列管线（source=recovery，同日同条目幂等去重）；
 * - 条目消失的引用由服务端诚实跳过（skipped 计数回显）。
 */

import { useState } from 'react'
import { Loader2, Undo2, X } from 'lucide-react'
import {
  useRecoveries,
  useRecoveryToQueueMutation,
} from '../api/queries'
import type { FeedRecoveryView } from '../api/types'
import { Button } from './ui/Button'

function RecoveryRow({
  recovery,
  onClose,
}: {
  recovery: FeedRecoveryView
  onClose: (id: string) => void
}) {
  const toQueue = useRecoveryToQueueMutation()
  const [result, setResult] = useState<string | null>(null)

  if (result !== null) {
    return (
      <li
        className="flex items-center gap-2 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-accent-soft)] px-2.5 py-1.5 text-xs text-[var(--lumi-accent-text)]"
        data-testid="recovery-added"
      >
        <Undo2 aria-hidden className="size-3.5" />
        {result}
      </li>
    )
  }
  const label = recovery.feedUrl
  return (
    <li className="flex flex-wrap items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1.5">
      <Undo2 aria-hidden className="size-3.5 shrink-0 text-[var(--lumi-accent-text)]" />
      <span className="min-w-0 flex-1 text-xs text-[var(--lumi-text-primary)]">
        <span className="block truncate">{label}</span>
        <span className="block text-[10px] text-[var(--lumi-text-tertiary)]">
          断更 {recovery.windowStart.slice(5, 16).replace('T', ' ')} →{' '}
          {recovery.windowEnd.slice(5, 16).replace('T', ' ')}，期间 {recovery.refCount} 篇
        </span>
      </span>
      {toQueue.isPending ? (
        <Loader2 aria-hidden className="size-3.5 animate-spin text-[var(--lumi-text-tertiary)]" />
      ) : (
        <Button
          size="sm"
          variant="primary"
          onClick={() =>
            toQueue.mutate(recovery.id, {
              onSuccess: (data) => {
                setResult(
                  `已加入补读队列：新增 ${data.added} 篇` +
                    (data.skipped > 0 ? `（${data.skipped} 篇已失效跳过）` : '') +
                    '。',
                )
                onClose(recovery.id)
              },
              onError: (error) => {
                const status = (error as { status?: number }).status
                setResult(
                  status === 409 ? '该窗口已加入过补读队列。' : '加入失败，请稍后重试。',
                )
              },
            })
          }
        >
          加入补读队列
        </Button>
      )}
    </li>
  )
}

/** 断更恢复横幅：有待处理窗口时才渲染（无窗口 = 零噪音）。 */
export function RecoveryBanner() {
  const recoveriesQuery = useRecoveries()
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const items = (recoveriesQuery.data ?? []).filter((item) => !dismissed.has(item.id))
  if (recoveriesQuery.isPending || recoveriesQuery.isError || items.length === 0) {
    return null
  }
  return (
    <section
      aria-label="断更恢复"
      data-testid="recovery-banner"
      className="mx-4 mb-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
    >
      <div className="flex items-center gap-2">
        <Undo2 aria-hidden className="size-4 text-[var(--lumi-accent-text)]" />
        <h3 className="text-sm font-semibold text-[var(--lumi-text-primary)]">断更恢复</h3>
        <span className="flex-1" />
        <button
          type="button"
          aria-label="关闭断更恢复横幅"
          onClick={() => setDismissed(new Set(items.map((item) => item.id)))}
          className="flex min-h-7 items-center rounded px-1 text-[var(--lumi-text-tertiary)] hover:bg-[var(--lumi-surface-hover)]"
        >
          <X aria-hidden className="size-4" />
        </button>
      </div>
      <ul className="mt-2 space-y-1">
        {items.map((recovery) => (
          <RecoveryRow
            key={recovery.id}
            recovery={recovery}
            onClose={(id) => setDismissed((prev) => new Set(prev).add(id))}
          />
        ))}
      </ul>
      {items.length > 0 && (
        <p className="mt-1 text-[10px] text-[var(--lumi-text-tertiary)]">
          断更期间的新文章一次性加入「今日必读」（可跳过、不重复）；失效条目自动略过。
        </p>
      )}
    </section>
  )
}

export default RecoveryBanner
