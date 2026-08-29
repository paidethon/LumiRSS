import { useEffect } from 'react'
import { useReaderUi } from '../store/reader-ui'
import Sidebar from './Sidebar'

/** MobileNavigationDrawer — <1024px 导航抽屉（0007）。
 *
 * 同一份 <Sidebar />：Desktop 它常驻第一栏，Mobile 它藏在 ☰ 后面
 * （不复制 MobileSidebar 组件）。
 *
 * 语义刻意不是 modal dialog：panel 是 <aside aria-label="导航">
 * landmark，无 aria-modal——0007 不实现 focus trap / modal focus
 * containment，声明 modal 语义却做不到 modal 行为会造成语义与
 * 行为不一致（未来升级 modal 需同时满足 WAI focus 要求）。
 *
 * 关闭：backdrop / ✕ / Escape / 完成一次导航选择（Sidebar 的
 * onNavigate 回调；非导航按钮如「重试」不会误关）。 */
export default function MobileNavigationDrawer() {
  const mobileSidebarOpen = useReaderUi((s) => s.mobileSidebarOpen)
  const closeMobileSidebar = useReaderUi((s) => s.closeMobileSidebar)

  // Escape 关闭：仅打开时挂监听，关闭即移除（不建 focus trap 框架）。
  useEffect(() => {
    if (!mobileSidebarOpen) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        closeMobileSidebar()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [mobileSidebarOpen, closeMobileSidebar])

  if (!mobileSidebarOpen) {
    return null
  }

  return (
    <div className="fixed inset-0 z-40 lg:hidden">
      {/* backdrop：真实 button（不把可点击 div 当 button），层级低于 panel */}
      <button
        type="button"
        aria-label="关闭导航"
        onClick={closeMobileSidebar}
        className="absolute inset-0 h-full w-full cursor-default bg-[var(--lumi-text-primary)]/40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
      />

      <aside
        id="mobile-navigation-drawer"
        aria-label="导航"
        className="absolute inset-y-0 left-0 flex w-[85%] max-w-80 flex-col overflow-y-auto border-r border-[var(--lumi-border)] bg-[var(--lumi-sidebar)] shadow-[var(--lumi-shadow-dialog)]"
        style={{
          paddingTop: 'var(--safe-top)',
          paddingBottom: 'var(--safe-bottom)',
          paddingLeft: 'max(0px, var(--safe-left))',
          paddingRight: 'max(0.75rem, var(--safe-right))',
        }}
      >
        <div className="flex items-center justify-between px-4 pb-1 pt-3">
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
      </aside>
    </div>
  )
}
