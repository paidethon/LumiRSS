import { useReaderUi } from '../store/reader-ui'
import Sidebar from './Sidebar'
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
 * 较大圆角（不影响窄屏内容宽度）；safe-area 四向计入。 */
export default function MobileNavigationDrawer() {
  const mobileSidebarOpen = useReaderUi((s) => s.mobileSidebarOpen)
  const closeMobileSidebar = useReaderUi((s) => s.closeMobileSidebar)

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
      </Sheet>
    </div>
  )
}
