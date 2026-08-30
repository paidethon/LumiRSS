/** SettingsButton — 设置入口按钮（0011 修正补充）。
 *
 * 从 SidebarHeader 抽出：展开态（圆形带边框）与折叠态（纯 icon）
 * 共用同一打开逻辑与响应式设置壳（桌面 Modal / 移动全屏页）——
 * 同一语义位置（Spec AC2）。 */

import { Settings } from 'lucide-react'
import { useState } from 'react'
import SettingsModal from './settings/SettingsModal'
import MobileSettingsScreen from './MobileSettingsScreen'
import { cx } from './ui/cx'

export default function SettingsButton({ collapsed }: { collapsed?: boolean }) {
  const [open, setOpen] = useState(false)

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="打开设置"
        title="设置"
        className={cx(
          'flex shrink-0 items-center justify-center rounded-full text-[var(--lumi-text-secondary)]',
          'transition-colors duration-[var(--lumi-motion-fast)]',
          'hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
          'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
          collapsed
            ? 'size-10 text-[var(--lumi-text-secondary)]'
            : 'size-9 border border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
        )}
      >
        <Settings aria-hidden className="size-4" />
      </button>

      {/* 响应式设置壳：桌面 Modal / 移动全屏页（CSS 各自隐藏另一种） */}
      <div className="hidden max-md:contents">
        <MobileSettingsScreen open={open} onClose={() => setOpen(false)} />
      </div>
      <div className="contents max-md:hidden">
        <SettingsModal open={open} onClose={() => setOpen(false)} />
      </div>
    </>
  )
}
