/** ShortcutsHelpDialog — 键盘快捷键速查（pool #06）。
 *
 * 「?」唤起；复用 Dialog primitive（Base UI 提供 Escape 关闭、焦点
 * trap、滚动锁、关闭还焦——不自建第二套模态行为）。
 * F037 收尾：显示当前生效绑定（用户覆盖优先，覆盖项带「已自定义」
 * 标注），支持单项 / 全部恢复默认；数据与设置中心快捷键页共用
 * SHORTCUT_ACTIONS 单一真源 + effectiveShortcuts 派生。 */

import { useEffect, useState } from 'react'
import { RotateCcw } from 'lucide-react'
import { Dialog } from './ui/Dialog'
import { effectiveShortcuts } from '../lib/keyboard-shortcuts'
import {
  loadCustomShortcuts,
  resetShortcut,
  saveCustomShortcuts,
} from '../lib/custom-shortcuts'

export function ShortcutsHelpDialog({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  // 每次打开重读 localStorage 覆盖表（与按键处理器同一读取约定）
  const [custom, setCustom] = useState<Record<string, string>>(() =>
    loadCustomShortcuts(),
  )
  useEffect(() => {
    if (open) setCustom(loadCustomShortcuts())
  }, [open])

  const persist = (next: Record<string, string>) => {
    setCustom(next)
    saveCustomShortcuts(next)
  }

  const rows = effectiveShortcuts(custom)
  const hasOverrides = Object.keys(custom).length > 0

  return (
    <Dialog open={open} onClose={onClose} title="键盘快捷键">
      <dl className="flex flex-col gap-2">
        {rows.map((shortcut) => (
          <div
            key={shortcut.id}
            className="flex items-center justify-between gap-4"
          >
            <dt className="flex min-w-0 items-center gap-2 text-sm text-[var(--lumi-text-secondary)]">
              <span className="truncate">{shortcut.action}</span>
              {shortcut.overridden && (
                <span className="shrink-0 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-text-tertiary)]">
                  已自定义
                </span>
              )}
            </dt>
            <dd className="flex shrink-0 items-center gap-1.5">
              <kbd className="rounded-[var(--lumi-radius-sm)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-0.5 font-mono text-xs text-[var(--lumi-text-primary)]">
                {shortcut.keys}
              </kbd>
              {shortcut.overridden && (
                <button
                  type="button"
                  aria-label={`恢复默认：${shortcut.action}`}
                  title="恢复默认"
                  onClick={() => persist(resetShortcut(custom, shortcut.id))}
                  className="flex size-7 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]"
                >
                  <RotateCcw aria-hidden className="size-3.5" />
                </button>
              )}
            </dd>
          </div>
        ))}
      </dl>
      {hasOverrides && (
        <div className="mt-3 flex justify-end">
          <button
            type="button"
            onClick={() => persist({})}
            className="flex items-center gap-1.5 rounded-[var(--lumi-radius-md)] px-2.5 py-1.5 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]"
          >
            <RotateCcw aria-hidden className="size-3.5" /> 全部恢复默认
          </button>
        </div>
      )}
    </Dialog>
  )
}

export default ShortcutsHelpDialog
