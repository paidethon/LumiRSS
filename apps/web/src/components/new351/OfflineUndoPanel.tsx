/** OfflineUndoPanel — NEW-359 离线阅读撤销栈面板。
 *
 * 两段式如实呈现：
 * - 未同步（本机排队意图）：逐项撤销（撤销 = 放弃这条从未到达服务器
 *   的意图，零网络）；
 * - 已同步：只读历史 + 明确标注「已同步——不能直接撤销，如需更改请
 *   再次操作」。
 * 空态诚实；清空按钮一次移除全部（含已同步历史）。 */

import { useState } from 'react'
import { Lock, RotateCcw, Trash2 } from 'lucide-react'
import {
  OFFLINE_UNDO_STACK_LIMIT,
  canUndoOfflineEntry,
  clearOfflineUndoStack,
  readOfflineUndoStack,
  undoOfflineEntry,
  type OfflineUndoEntry,
} from '../../lib/offline-undo-stack'
import { Dialog } from '../ui/Dialog'
import { Button } from '../ui/Button'

export function OfflineUndoPanel({ onClose }: { onClose: () => void }) {
  const [stack, setStack] = useState<OfflineUndoEntry[]>(() => readOfflineUndoStack())
  const [rejectedId, setRejectedId] = useState<string | null>(null)

  const pending = stack.filter((entry) => canUndoOfflineEntry(entry))
  const synced = stack.filter((entry) => !canUndoOfflineEntry(entry))

  const undo = (id: string) => {
    const removed = undoOfflineEntry(id)
    if (removed === null) {
      // 已同步条目的撤销请求：明确拒绝并如实提示（不静默失败）。
      setRejectedId(id)
      return
    }
    setRejectedId(null)
    setStack(readOfflineUndoStack())
  }

  const clearAll = () => {
    clearOfflineUndoStack()
    setStack([])
    setRejectedId(null)
  }

  return (
    <Dialog open onClose={onClose} title="离线阅读撤销栈" panelClassName="max-w-lg">
      <div className="flex flex-col gap-4">
        <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          记录本设备的个人操作（标已读 / 收藏 / 稍后读）：
          <strong>未同步</strong>的条目可逐项撤销（放弃本机排队意图）；
          <strong>已同步</strong>的条目已在服务器生效——本栈不能直接撤销。
        </p>

        <section aria-label="未同步操作" data-testid="n359-pending">
          <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">
            未同步（{pending.length}）
          </h3>
          {pending.length === 0 ? (
            <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
              没有待撤销的本机操作。离线时失败的批量动作会记在这里。
            </p>
          ) : (
            <ul className="mt-1.5 flex flex-col gap-1">
              {pending.map((entry) => (
                <li
                  key={entry.id}
                  data-n359-pending-item={entry.entryRef}
                  className="flex min-h-11 items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1"
                >
                  <span className="min-w-0 flex-1 truncate text-xs text-[var(--lumi-text-primary)]">
                    {entry.label} · {entry.entryRef}
                  </span>
                  <button
                    type="button"
                    aria-label={`撤销 ${entry.label} ${entry.entryRef}`}
                    onClick={() => undo(entry.id)}
                    className="flex min-h-11 shrink-0 items-center gap-1 rounded-[var(--lumi-radius-sm)] px-2 text-xs text-[var(--lumi-accent-text)] hover:bg-[var(--lumi-surface-hover)]"
                  >
                    <RotateCcw aria-hidden className="size-3.5" />
                    撤销
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-label="已同步操作" data-testid="n359-synced">
          <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">
            已同步（{synced.length}）
          </h3>
          {synced.length === 0 ? (
            <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
              暂无已同步记录。
            </p>
          ) : (
            <ul className="mt-1.5 flex flex-col gap-1">
              {synced.map((entry) => (
                <li
                  key={entry.id}
                  data-n359-synced-item={entry.entryRef}
                  className="flex min-h-11 items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1"
                >
                  <Lock aria-hidden className="size-3.5 shrink-0 text-[var(--lumi-text-tertiary)]" />
                  <span className="min-w-0 flex-1 truncate text-xs text-[var(--lumi-text-secondary)]">
                    {entry.label} · {entry.entryRef}
                  </span>
                  {rejectedId === entry.id && (
                    <span role="alert" className="shrink-0 text-xs text-[var(--lumi-danger)]">
                      已同步，不能直接撤销
                    </span>
                  )}
                  <button
                    type="button"
                    aria-label={`尝试撤销 ${entry.label} ${entry.entryRef}`}
                    onClick={() => undo(entry.id)}
                    className="flex min-h-11 shrink-0 items-center rounded-[var(--lumi-radius-sm)] px-2 text-xs text-[var(--lumi-text-tertiary)] hover:bg-[var(--lumi-surface-hover)]"
                  >
                    撤销
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-1.5 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
            已同步的条目如需更改，请再次执行相应操作（读 / 未读、收藏 /
            取消收藏）——那是一次新的正常操作，不是撤销。
          </p>
        </section>

        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-[var(--lumi-text-tertiary)]">
            栈容量 {stack.length}/{OFFLINE_UNDO_STACK_LIMIT}（超出自动逐出最旧）
          </span>
          <Button
            variant="ghost"
            size="sm"
            data-testid="n359-clear"
            onClick={clearAll}
            disabled={stack.length === 0}
          >
            <Trash2 aria-hidden className="size-3.5" />
            清空记录
          </Button>
        </div>
      </div>
      <Button variant="secondary" className="min-h-11" onClick={onClose}>
        关闭
      </Button>
    </Dialog>
  )
}

export default OfflineUndoPanel
