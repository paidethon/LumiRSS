/** SidebarHeader — 侧边栏品牌区（0011 Gate 1，参考图 01-sidebar）。
 *
 * 同一组件用于桌面固定侧栏与移动导航抽屉：LumiRSS + 流光阅源 副标题
 * + 右上角圆形设置图标按钮。设置入口的唯一位置（0011 起侧边栏底部
 * 旧设置行与底部 Tab 设置均已移除）。
 *
 * 响应式设置壳（0010a 语义）：桌面（≥768）开 SettingsModal，
 * 移动（<768）开 MobileSettingsScreen 全屏页——同一语义位置。 */

import { Settings } from 'lucide-react'
import { useState } from 'react'
import SettingsModal from './settings/SettingsModal'
import MobileSettingsScreen from './MobileSettingsScreen'

export default function SidebarHeader() {
  const [open, setOpen] = useState(false)

  return (
    <div className="flex items-start justify-between gap-2 px-2.5 pb-1 pt-2">
      <div className="min-w-0">
        <h1 className="text-base font-semibold tracking-tight text-[var(--lumi-text-primary)]">
          LumiRSS
        </h1>
        <p className="text-xs text-[var(--lumi-text-tertiary)]">流光阅源</p>
      </div>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="打开设置"
        title="设置"
        className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-full border border-[var(--lumi-border)] bg-[var(--lumi-surface)] text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
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
    </div>
  )
}
