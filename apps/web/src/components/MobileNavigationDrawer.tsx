import { lazy, Suspense, useState } from 'react'
import { Command, History, EyeOff } from 'lucide-react'
import { useReaderUi } from '../store/reader-ui'
import { COMMAND_PALETTE_TOGGLE_EVENT } from '../lib/keyboard-shortcuts'
import { isPrivacyEnabled, setPrivacyMask } from '../lib/privacy-mask'
import Sidebar from './Sidebar'
// bundle guard：base-ui Drawer（约 20K min）不进首屏 chunk——Sheet 条件
// 挂载（mobileSidebarOpen 才挂）+ lazy；模块级 warm import 让 chunk 在
// 应用启动时并行预热（动态 import 不进 entry，与「遮罩/✕/Escape 关闭、
// 打开即 Sidebar 可见」的行为契约不变；打开瞬间 chunk 未就绪时显示
// 短暂空白后自动出现）。
type SheetComponent = typeof import('./ui/Sheet')['Sheet']
let LoadedSheet: SheetComponent | null = null
// 预热：应用启动即并行加载（动态 import 不进 entry chunk）。
const sheetLoad: Promise<void> = import('./ui/Sheet').then((m) => {
  LoadedSheet = m.Sheet
})
void sheetLoad

/** 同步可用的 Sheet：模块就绪（测试 beforeEach 预解析/生产预热完成）
 * 后直接同步渲染——不走 React.lazy 的「首次渲染必挂起」路径，抽屉打开
 * 的同步结构断言（fireEvent 后立即查 DOM）确定性成立。 */
function DrawerSheet(props: React.ComponentProps<SheetComponent>) {
  if (LoadedSheet !== null) {
    const S = LoadedSheet
    return <S {...props} />
  }
  throw sheetLoad // 尚未就绪 → 由 Suspense 兜底（fallback null）
}

// Bundle guard（Phase K）：命令面板/最近阅读只在抽屉里用——懒加载分包，
// 不占首屏预算（键盘事件监听在 CommandPalette 模块内部，首次交互前
// 面板未挂载也不影响 toggle 事件的时序：事件由 keyboard-shortcuts 派发，
// 面板挂载后即开始监听）。
const RecentReads = lazy(() => import('./RecentReads'))
const CommandPalette = lazy(() => import('./CommandPalette'))

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
  // F113：演示隐私遮罩（device-local 开关；真实替换 [data-privacy-text]）
  const [privacyOn, setPrivacyOn] = useState(isPrivacyEnabled)

  const togglePrivacy = () => {
    const next = !privacyOn
    setPrivacyOn(next)
    setPrivacyMask(next)
  }

  const openCommandPalette = () => {
    window.dispatchEvent(new CustomEvent(COMMAND_PALETTE_TOGGLE_EVENT))
  }

  return (
    <div className="lg:hidden">
      {mobileSidebarOpen && (
      <Suspense fallback={null}>
      <DrawerSheet
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
          {/* F113：演示隐私（开启后标题/来源等文本替换为 ▮；退出/刷新恢复） */}
          <button
            type="button"
            data-testid="drawer-privacy-demo"
            aria-pressed={privacyOn}
            onClick={togglePrivacy}
            className="flex min-h-11 items-center gap-2.5 rounded-[var(--lumi-radius-md)] px-2 text-sm text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            <EyeOff aria-hidden className="size-4 shrink-0" />
            {privacyOn ? '演示隐私：开（点击退出）' : '演示隐私'}
          </button>
        </div>
      </DrawerSheet>
      </Suspense>
      )}

      {/* F10：最近阅读覆盖层（z 高于抽屉；Escape/遮罩/✕ 关闭） */}
      <Suspense fallback={null}>
        <RecentReads open={recentReadsOpen} onClose={() => setRecentReadsOpen(false)} />
      </Suspense>

      {/* F30：命令面板（常驻挂载监听 Ctrl/⌘+K 事件；关闭时零渲染） */}
      <Suspense fallback={null}>
        <CommandPalette />
      </Suspense>
    </div>
  )
}
