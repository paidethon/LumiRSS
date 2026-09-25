/** WorkspaceCompare — N106 工作区双栏对读。
 *
 * 从当前工作区挑 2 个条目 → 复用 CompareRead 双栏并排（复用既有
 * ArticleContent DOMPurify 渲染边界，不复制实现）。关键语义：
 * - 锚点同步是显式按钮（A→B 滚动跳转），绝不自动跟随；
 * - iPad 横屏（宽 ≥768px，与 CompareRead 的桌面判定一致）双栏可用；
 * - 窄屏沿用 CompareRead 既有的无障碍 A/B 切换（role=tablist）；
 * - 窗格空闲休眠由 CompareRead 内建（N107）。
 */

import { useState } from 'react'
import { GitCompareArrows } from 'lucide-react'
import CompareRead from './CompareRead'
import { Button } from './ui/Button'
import { cx } from './ui/cx'

export interface WorkspaceCompareItem {
  ref: string
  title: string
}

export default function WorkspaceCompare({
  items,
  onClose,
}: {
  items: WorkspaceCompareItem[]
  onClose: () => void
}) {
  const [a, setA] = useState<string | null>(null)
  const [b, setB] = useState<string | null>(null)
  const ready = a !== null && b !== null && a !== b

  const selectClass = cx(
    'min-h-11 w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)]',
    'bg-[var(--lumi-surface)] px-3 text-sm text-[var(--lumi-text-primary)]',
    'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
  )

  if (ready) {
    return <CompareRead refs={[a, b] as [string, string]} onClose={onClose} anchorSync />
  }

  return (
    <section
      aria-label="工作区双栏对读"
      data-testid="workspace-compare-picker"
      className="flex h-full flex-col items-center justify-center gap-4 p-6"
    >
      <div className="flex items-center gap-2 text-sm font-semibold text-[var(--lumi-text-primary)]">
        <GitCompareArrows aria-hidden className="size-4" />
        选择两个条目开始双栏对读
      </div>
      <div className="grid w-full max-w-md gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">A 篇</span>
          <select
            data-testid="compare-pick-a"
            className={selectClass}
            value={a ?? ''}
            onChange={(e) => setA(e.target.value || null)}
          >
            <option value="">选择 A 篇…</option>
            {items.map((item) => (
              <option key={item.ref} value={item.ref} disabled={item.ref === b}>
                {item.title}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">B 篇</span>
          <select
            data-testid="compare-pick-b"
            className={selectClass}
            value={b ?? ''}
            onChange={(e) => setB(e.target.value || null)}
          >
            <option value="">选择 B 篇…</option>
            {items.map((item) => (
              <option key={item.ref} value={item.ref} disabled={item.ref === a}>
                {item.title}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs text-[var(--lumi-text-tertiary)]">
          两篇选定后自动进入双栏对读。
        </span>
        <Button variant="ghost" size="sm" onClick={onClose}>
          取消
        </Button>
      </div>
    </section>
  )
}
