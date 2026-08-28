import { useReaderUi } from './store/reader-ui'
import EntryList from './components/EntryList'
import MobileHeader from './components/MobileHeader'
import MobileNavigationDrawer from './components/MobileNavigationDrawer'
import Reader from './components/Reader'
import Sidebar from './components/Sidebar'

/** 响应式 Web Shell（0007）：同一棵组件树，布局由 CSS 决定。
 *
 * >=1024px（lg）：保持 0005/0006 三栏，各自滚动，h-dvh 整页不滚动。
 * <1024px：Mobile Header + 单主内容区 + 导航抽屉——
 *   selectedEntryRef == null → Entry List（既有状态推导，非新增
 *   mobilePane state；selectedEntryRef 只读，不复制 server state）；
 *   selectedEntryRef != null → Reader 全屏替换列表（点击 ← 返回 =
 *   selectEntry(null)，TanStack Query cache 恢复显示，不 reload）。 */
export default function App() {
  const selectedEntryRef = useReaderUi((s) => s.selectedEntryRef)

  return (
    <div className="flex h-dvh flex-col">
      {/* Mobile 顶栏：<1024 显示；>=1024 不占任何布局空间 */}
      <MobileHeader />

      <main className="flex min-h-0 flex-1 flex-col lg:grid lg:grid-cols-[240px_400px_1fr]">
        {/* Desktop Sidebar：<1024 隐藏（导航由 Drawer 承载同一份 Sidebar） */}
        <aside className="hidden min-w-0 overflow-y-auto border-r border-[var(--border)] bg-[var(--surface)] lg:block">
          <Sidebar />
        </aside>

        {/* Entry List：手机上仅无选中时可见；桌面始终显示 */}
        <section
          className={`flex min-h-0 min-w-0 flex-col overflow-hidden border-r border-[var(--border)] bg-[var(--surface)] ${
            selectedEntryRef === null ? '' : 'hidden lg:flex'
          }`}
        >
          <EntryList />
        </section>

        {/* Reader：手机上仅选中时可见；桌面始终显示 */}
        <section
          className={`min-h-0 min-w-0 bg-[var(--surface)] ${
            selectedEntryRef === null ? 'hidden lg:block' : 'lg:block'
          }`}
        >
          <Reader />
        </section>
      </main>

      {/* Mobile 导航抽屉：仅 <1024 有意义；关闭时不渲染 */}
      <MobileNavigationDrawer />
    </div>
  )
}
