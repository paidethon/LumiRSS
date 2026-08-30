import { PanelLeft, PanelLeftClose } from 'lucide-react'
import { useReaderUi } from './store/reader-ui'
import { useAppSettings } from './store/app-settings'
import { useKeyboardShortcuts } from './lib/keyboard-shortcuts'
import EntryList from './components/EntryList'
import MobileHeader from './components/MobileHeader'
import MobileNavigationDrawer from './components/MobileNavigationDrawer'
import MobileTabBar from './components/MobileTabBar'
import Reader from './components/Reader'
import Sidebar from './components/Sidebar'
import { PaneSeparator } from './components/ui/PaneSeparator'

/** 分栏约束（Spec §设计规格，借鉴 OrigRead 约束模型） */
const SIDEBAR_MIN = 220
const SIDEBAR_MAX = 300
const TIMELINE_MIN = 360
const TIMELINE_MAX = 460

/** 响应式 Web Shell（0010 Gate C：三栏可拖拽/可折叠 + 持久化）。
 *
 * >=1024px（lg）：Sidebar | sep | Timeline | sep | Reader。
 *   - Grid 改 flex + store 宽度（app-settings 持久化，刷新恢复）；
 *   - PaneSeparator：拖拽 clamp / 键盘 ←→ / 双击重置；
 *   - 折叠：Sidebar → 隐藏（图标条展开由 Header 按钮承担简化实现：
 *     折叠 = 完全隐藏 + 顶角展开按钮），Timeline 折叠 = 隐藏
 *     （记忆宽度，展开恢复）；
 *   - <1024px 自动忽略分栏状态（硬边界 5：移动端行为与 0009 一致）。
 * <1024px：Mobile Header + 单主内容区 + 导航抽屉（0007/0009 语义不变）。 */
export default function App() {
  const selectedEntryRef = useReaderUi((s) => s.selectedEntryRef)
  // 0010 Gate B：全局键盘快捷键（j/k/u/s；输入框聚焦时不劫持）
  useKeyboardShortcuts()

  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)

  const sidebarCollapsed = settings.sidebarCollapsed
  const timelineCollapsed = settings.timelineCollapsed

  return (
    <div className="flex h-dvh flex-col bg-[var(--lumi-canvas)]">
      {/* Mobile 顶栏：<1024 显示；>=1024 不占任何布局空间 */}
      <MobileHeader />

      <main className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {/* ===== 桌面 Sidebar（可折叠 + 可拖宽，仅 lg） ===== */}
        {sidebarCollapsed ? (
          <div className="hidden items-start p-2 lg:flex">
            <button
              type="button"
              onClick={() => update({ sidebarCollapsed: false })}
              aria-label="展开侧栏"
              className="flex size-8 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
            >
              <PanelLeft aria-hidden className="size-4" />
            </button>
          </div>
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

        {/* ===== Timeline（可折叠，仅 lg 有分隔条） ===== */}
        <section
          className={`flex min-h-0 min-w-0 flex-col overflow-hidden bg-[var(--lumi-surface)] ${
            selectedEntryRef === null ? '' : 'hidden lg:flex'
          }`}
          style={
            timelineCollapsed
              ? undefined
              : { flexBasis: settings.timelineWidth, flexGrow: 0, flexShrink: 0 }
          }
        >
          <EntryList />
        </section>

        {/* Timeline 折叠态：展开按钮（桌面） */}
        {timelineCollapsed && (
          <div className="hidden min-h-0 items-center bg-[var(--lumi-surface)] lg:flex">
            <button
              type="button"
              onClick={() => update({ timelineCollapsed: false })}
              aria-label="展开文章列表"
              className="flex h-9 w-9 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
            >
              <PanelLeft aria-hidden className="size-4 rotate-180" />
            </button>
          </div>
        )}

        {/* Timeline | Reader 分隔条（未折叠且未移动端时） */}
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

        {/* ===== Reader（flex-1 占满剩余） ===== */}
        <section
          className={`min-h-0 min-w-0 flex-1 bg-[var(--lumi-surface)] ${
            selectedEntryRef === null ? 'hidden lg:block' : 'lg:block'
          }`}
        >
          <Reader />
        </section>
      </main>

      {/* Mobile 导航抽屉：仅 <1024 有意义；关闭时不渲染 */}
      <MobileNavigationDrawer />

      {/* 0010 Gate D：<768 底部 Tab（时间线/收藏/设置）；Reader 打开时隐藏 */}
      <MobileTabBar />
    </div>
  )
}
