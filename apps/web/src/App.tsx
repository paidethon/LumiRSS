import { PanelLeft, PanelLeftClose } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { useReaderUi } from './store/reader-ui'
import { useAppSettings } from './store/app-settings'
import { useKeyboardShortcuts } from './lib/keyboard-shortcuts'
import EntryList from './components/EntryList'
import MobileHeader from './components/MobileHeader'
import MobileNavigationDrawer from './components/MobileNavigationDrawer'
import MobileTabBar from './components/MobileTabBar'
import Reader from './components/Reader'
import Sidebar from './components/Sidebar'
import SidebarCollapsedRail from './components/SidebarCollapsedRail'
import FavoritesPage from './components/pages/FavoritesPage'
import SearchPage from './components/pages/SearchPage'
import SubscriptionsPage from './components/pages/SubscriptionsPage'
import { PaneSeparator } from './components/ui/PaneSeparator'

/** 分栏约束（Spec §设计规格，借鉴 OrigRead 约束模型） */
const SIDEBAR_MIN = 220
const SIDEBAR_MAX = 300
const TIMELINE_MIN = 360
const TIMELINE_MAX = 460

/** 响应式 Web Shell（0010 Gate C + 0011）。
 *
 * >=1024px（lg）：Sidebar | sep | Timeline | sep | Reader。
 *   - 栏宽由 app-settings 驱动（拖拽/持久化）；
 *   - 0011 阻断修复 §25–§28：Timeline 隐藏 = 完全退出布局列（不残留
 *     窄栏），隐藏时 toggle 移到 Reader 列顶部；selection 清空时
 *     自动恢复 Timeline（§28 auto-restore）。
 * <1024px：Mobile Header + 单主内容区（AppSection 切换）+ 导航抽屉。 */
export default function App() {
  const section = useReaderUi((s) => s.section)
  const selectedEntryRef = useReaderUi((s) => s.selectedEntryRef)
  // 0010 Gate B：全局键盘快捷键（j/k/u/s；输入框聚焦时不劫持）
  useKeyboardShortcuts()

  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)

  const sidebarCollapsed = settings.sidebarCollapsed
  const timelineCollapsed = settings.timelineCollapsed

  // §28：selection 从非空 → 空且 Timeline 当前隐藏 → 自动恢复（避免
  // “侧栏 + 巨大空白 Reader + 文章列表被藏”的状态）。基于 prev ref
  // 的转移检测——用户主动隐藏时 selection 不变，不会误触发。
  const prevSelectionRef = useRef(selectedEntryRef)
  useEffect(() => {
    if (
      prevSelectionRef.current !== null &&
      selectedEntryRef === null &&
      useAppSettings.getState().settings.timelineCollapsed
    ) {
      update({ timelineCollapsed: false })
    }
    prevSelectionRef.current = selectedEntryRef
  }, [selectedEntryRef, update])

  return (
    <div className="flex h-dvh flex-col bg-[var(--lumi-canvas)]">
      {/* Mobile 顶栏：<1024 显示；>=1024 不占任何布局空间 */}
      <MobileHeader />

      <main className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {/* ===== 桌面 Sidebar（可折叠 + 可拖宽，仅 lg） =====
            0011 修正补充：折叠态改为 SidebarCollapsedRail（icon-only
            导航栏，含 tooltip/active/disabled/设置），不再只渲染展开按钮 */}
        {sidebarCollapsed ? (
          <SidebarCollapsedRail />
        ) : (
          <>
            <aside
              className="hidden shrink-0 overflow-y-auto bg-[var(--lumi-sidebar)] lg:block"
              style={{ width: settings.sidebarWidth }}
            >
              <div className="sticky top-0 z-10 flex justify-end bg-[var(--lumi-sidebar)] pr-2 pt-2">
                <button
                  type="button"
                  onClick={() => update({ sidebarCollapsed: true })}
                  aria-label="折叠侧栏"
                  className="flex size-7 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                >
                  <PanelLeftClose aria-hidden className="size-4" />
                </button>
              </div>
              <Sidebar />
            </aside>
            <div className="hidden lg:flex">
              <PaneSeparator
                label="侧栏宽度"
                value={settings.sidebarWidth}
                min={SIDEBAR_MIN}
                max={SIDEBAR_MAX}
                onChange={(w) => update({ sidebarWidth: w })}
                onReset={() => update({ sidebarWidth: 240 })}
              />
            </div>
          </>
        )}

        {/* ===== 移动端一级页面区（0011）：订阅/搜索/收藏，仅 <1024 =====
            （selectSection 会清空 selectedEntryRef，与 Reader 不共存）
            0014a Gate 2：移动端从收藏/搜索等 section 打开文章时，section
            页面必须让位——Reader 全屏（与首页 Timeline 相同的
            hidden-layout 契约），back 后返回原列表（section/view/scope
            不变）。桌面 lg 恒隐藏本区（用时间线三栏）。 */}
        {section !== 'home' && (
          <section
            className={`flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto bg-[var(--lumi-surface)] lg:hidden ${
              selectedEntryRef !== null ? 'max-lg:hidden' : ''
            }`}
            aria-label={section === 'subscriptions' ? '订阅' : section === 'search' ? '搜索' : '收藏'}
          >
            {section === 'subscriptions' && <SubscriptionsPage />}
            {section === 'search' && <SearchPage />}
            {section === 'favorites' && <FavoritesPage />}
          </section>
        )}

        {/* ===== Timeline（桌面可隐藏，仅 lg 有分隔条；移动端 home section 显示） =====
            0011 阻断修复：桌面栏宽不再用 inline flexBasis（<1024 时 main 为
            flex-col，flexBasis 会把列表高度锁死在 360–460px）——CSS 变量 +
            响应式 flex 类：<1024px w-full + flex-1；≥1024px lg:basis-[宽度]。
            0011 §25/§26：隐藏 = 桌面完全退出布局列（不渲染 section 与分隔
            条，无窄栏）；toggle 移到 Reader 列顶（隐藏时）+ 列表头（可见时）。
            移动端不受 timelineCollapsed 影响（该状态是桌面概念）。 */}
        <section
          className={`flex min-h-0 min-w-0 w-full flex-1 flex-col overflow-hidden bg-[var(--lumi-surface)] lg:w-auto lg:flex-none lg:basis-[var(--lumi-timeline-width)] ${
            selectedEntryRef === null ? '' : 'hidden lg:flex'
          }${section !== 'home' ? ' max-lg:hidden' : ''}${
            timelineCollapsed ? ' lg:hidden' : ''
          }`}
          style={{ '--lumi-timeline-width': `${settings.timelineWidth}px` } as React.CSSProperties}
        >
          <EntryList />
        </section>

        {/* Timeline | Reader 分隔条（未隐藏且未移动端时） */}
        {!timelineCollapsed && (
          <div className="hidden lg:flex">
            <PaneSeparator
              label="文章列表宽度"
              value={settings.timelineWidth}
              min={TIMELINE_MIN}
              max={TIMELINE_MAX}
              onChange={(w) => update({ timelineWidth: w })}
              onReset={() => update({ timelineWidth: 400 })}
            />
          </div>
        )}

        {/* ===== Reader（flex-1 占满剩余） =====
            0011 §27：Timeline 隐藏时 toggle 移到 Reader 列顶部左侧
            （同一功能的 toggle，非第二个功能；不产生纵向窄栏）。 */}
        <section
          className={`min-h-0 min-w-0 flex-1 bg-[var(--lumi-surface)] ${
            selectedEntryRef === null ? 'hidden lg:block' : 'lg:block'
          }`}
        >
          {timelineCollapsed && (
            <div className="hidden items-center border-b border-[var(--lumi-separator)] px-2 py-1.5 lg:flex">
              <button
                type="button"
                onClick={() => update({ timelineCollapsed: false })}
                aria-label="显示文章列表"
                aria-pressed={false}
                title="显示文章列表"
                className="flex size-8 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
              >
                <PanelLeft aria-hidden className="size-4 rotate-180" />
              </button>
            </div>
          )}
          <Reader />
        </section>
      </main>

      {/* Mobile 导航抽屉：仅 <1024 有意义；关闭时不渲染 */}
      <MobileNavigationDrawer />

      {/* 0011 Gate 1：<768 底部导航岛（首页/订阅/搜索/收藏）；Reader 打开时隐藏 */}
      <MobileTabBar />
    </div>
  )
}
