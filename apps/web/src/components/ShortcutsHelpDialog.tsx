/** ShortcutsHelpDialog — 键盘快捷键速查（pool #06）。
 *
 * 「?」唤起；复用 Dialog primitive（Base UI 提供 Escape 关闭、焦点
 * trap、滚动锁、关闭还焦——不自建第二套模态行为）。速查数据与设置
 * 中心的快捷键页共用 SHORTCUTS 单一真源。 */

import { Dialog } from './ui/Dialog'
import { SHORTCUTS } from '../lib/keyboard-shortcuts'

export function ShortcutsHelpDialog({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  return (
    <Dialog open={open} onClose={onClose} title="键盘快捷键">
      <dl className="flex flex-col gap-2">
        {SHORTCUTS.map((shortcut) => (
          <div
            key={shortcut.keys}
            className="flex items-center justify-between gap-4"
          >
            <dt className="text-sm text-[var(--lumi-text-secondary)]">
              {shortcut.action}
            </dt>
            <dd>
              <kbd className="rounded-[var(--lumi-radius-sm)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-0.5 font-mono text-xs text-[var(--lumi-text-primary)]">
                {shortcut.keys}
              </kbd>
            </dd>
          </div>
        ))}
      </dl>
    </Dialog>
  )
}

export default ShortcutsHelpDialog
