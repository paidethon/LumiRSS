/** MobileOrganizeBar — NEW-354 移动批量整理模式的范围条。
 *
 * 整理模式（列表多选）在移动端的**显式范围声明**：进入即固定展示
 * 「视图 / 信息源范围 / 本页已加载 / 已选」，与既有批量操作栏
 * （EntryList F07 batch-bar）上下配合构成统一操作面；「退出整理」走
 * EntryList 的 exitSelectMode——一次退出清空选择 / 批量失败清单 /
 * 运行标志，绝不遗留选择状态。
 *
 * 本组件只负责范围与计数的展示 + 退出入口；全部动作仍在既有批量栏
 * （单一操作面，不复制第二套批量逻辑）。 */

import { X } from 'lucide-react'
import {
  organizeCountLine,
  organizeScopeLine,
  type OrganizeScopeInput,
} from '../../lib/list-organize'

export interface MobileOrganizeBarProps {
  scope: OrganizeScopeInput
  /** 批量上限（与 EntryList BATCH_LIMIT 同值传入）。 */
  batchLimit: number
  onExit: () => void
}

export function MobileOrganizeBar({ scope, batchLimit, onExit }: MobileOrganizeBarProps) {
  return (
    <div
      role="status"
      aria-label="整理模式范围"
      data-testid="n354-organize-bar"
      className="border-b border-[var(--lumi-separator)] bg-[var(--lumi-surface)] px-3 py-2"
    >
      <div className="flex items-center gap-2">
        <p className="min-w-0 flex-1 truncate text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          <span className="font-medium text-[var(--lumi-text-primary)]">整理模式</span>
          <span className="mx-1.5" aria-hidden="true">·</span>
          {organizeScopeLine(scope)}
        </p>
        <button
          type="button"
          data-testid="n354-exit-organize"
          onClick={onExit}
          className="flex min-h-11 shrink-0 items-center gap-1 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-2.5 py-1 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        >
          <X aria-hidden className="size-3.5" />
          退出整理
        </button>
      </div>
      <p
        data-testid="n354-organize-count"
        aria-live="polite"
        className="mt-0.5 text-xs tabular-nums leading-relaxed text-[var(--lumi-text-tertiary)]"
      >
        {organizeCountLine(scope, batchLimit)}
      </p>
    </div>
  )
}

export default MobileOrganizeBar
