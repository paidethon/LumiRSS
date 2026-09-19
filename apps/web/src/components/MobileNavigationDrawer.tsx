import { useState } from 'react'
import { Command, History } from 'lucide-react'
import { useReaderUi } from '../store/reader-ui'
import { COMMAND_PALETTE_TOGGLE_EVENT } from '../lib/keyboard-shortcuts'
import Sidebar from './Sidebar'
import RecentReads from './RecentReads'
import CommandPalette from './CommandPalette'
import { Sheet } from './ui/Sheet'

/** MobileNavigationDrawer — <1024px 导航抽屉（0007 创建；0011 Gate 2
 * 升级为完整 modal）。
 *
 * 同一份 <Sidebar />：Desktop 它常驻第一栏，Mobile 它藏在 ☰ 后面
 * （不复制 MobileSidebar 组件）。
 *
 * 0011 Gate 2（用户批准）：升级为完整 modal 语义，基于增强后的
 * Sheet primitive（不再手写弹层）：
 * - role="dialog" + aria-modal + focus trap（Tab 循环在面板内）；
 * - 初始焦点：第一个可聚焦元素（✕ 关闭钮）；关闭后焦点恢复触发按钮；
 * - 打开时锁定背景滚动（body overflow hidden）；
 * - 关闭途径：Escape / 遮罩点击 / ✕ / 完成一次导航选择（Sidebar 的
 *   onNavigate 回调；非导航按钮如「重试」不会误关）。
 *
 * 宽度用 min(85vw, 20rem) 表达（不锁死参考图机型尺寸）；右侧上下
 * 较大圆角（不影响窄屏内容宽度）；safe-area 四向计入。
 *
 * 2026-09 批次新增（工具入口，渲染于抽屉底部）：
 * - F10「最近阅读」：打开本地历史面板（覆盖层，z 高于抽屉）；
 * - F30「命令面板」：派发 COMMAND_PALETTE_TOGGLE_EVENT——CommandPalette
 *   常驻挂载（始终在树），自持开关与返回链登记，桌面端 Ctrl/⌘+K 同通道。
 *   抽屉保持打开（面板盖在其上，后退/Escape 逐层关闭）。 */
export default function MobileNavigationDrawer() {
  const mobileSidebarOpen = useReaderUi((s) => s.mobileSidebarOpen)
  const closeMobileSidebar = useReaderUi((s) => s.closeMobileSidebar)
  // F10：最近阅读面板（渲染在 Sheet 之外——覆盖层不参与抽屉的 Drawer 行为）
  const [recentReadsOpen, setRecentReadsOpen] = useState(false)

  const openCommandPalette = () => {
    window.dispatchEvent(new CustomEvent(COMMAND_PALETTE_TOGGLE_EVENT))
  }

  return (
    <div className="lg:hidden">
      <Sheet
        open={mobileSidebarOpen}
        onClose={closeMobileSidebar}
        label="导航"
        id="mobile-navigation-drawer"
        panelClassName="flex w-[min(85vw,20rem)] flex-col overflow-y-auto rounded-r-[var(--lumi-radius-xl)] border-r-0 bg-[var(--lumi-sidebar)] pr-1 pb-[max(0.5rem,var(--safe-bottom))] pl-[max(0,var(--safe-left))]"
      >
        <div
          className="flex items-center justify-between px-4 pb-1 pt-3"
          style={{
            paddingTop: 'max(0.75rem, var(--safe-top))',
            paddingLeft: 'max(1rem, var(--safe-left))',
          }}
        >
          <span className="text-sm font-semibold text-[var(--lumi-text-secondary)]">
            导航
          </span>
          <button
            type="button"
            onClick={closeMobileSidebar}
            aria-label="关闭"
            className="flex min-h-11 min-w-11 items-center justify-center rounded-[var(--lumi-radius-md)] px-2 text-lg leading-none text-[var(--lumi-text-secondary)] transition-colors hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            ✕
          </button>
        </div>

        <Sidebar onNavigate={closeMobileSidebar} />

        {/* 工具入口（F10 / F30）：44px 触控目标，icon 带可读文案 */}
        <div
          className="mt-2 flex shrink-0 flex-col gap-0.5 border-t border-[var(--lumi-separator)] px-3 pb-1 pt-2"
          style={{ paddingBottom: 'max(0.5rem, var(--safe-bottom))' }}
        >
          <button
            type="button"
            data-testid="drawer-recent-reads"
            onClick={() => setRecentReadsOpen(true)}
            className="flex min-h-11 items-center gap-2.5 rounded-[var(--lumi-radius-md)] px-2 text-sm text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            <History aria-hidden className="size-4 shrink-0" />
            最近阅读
          </button>
          <button
            type="button"
            data-testid="drawer-command-palette"
            onClick={openCommandPalette}
            className="flex min-h-11 items-center gap-2.5 rounded-[var(--lumi-radius-md)] px-2 text-sm text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            <Command aria-hidden className="size-4 shrink-0" />
            命令面板
          </button>
        </div>
      </Sheet>

      {/* F10：最近阅读覆盖层（z 高于抽屉；Escape/遮罩/✕ 关闭） */}
      <RecentReads open={recentReadsOpen} onClose={() => setRecentReadsOpen(false)} />

      {/* F30：命令面板（常驻挂载监听 Ctrl/⌘+K 事件；关闭时零渲染） */}
      <CommandPalette />
    </div>
  )
}
