import { PanelLeft, PanelLeftClose } from 'lucide-react'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { useReaderUi } from './store/reader-ui'
import { useAppSettings } from './store/app-settings'
import { useKeyboardShortcuts } from './lib/keyboard-shortcuts'
import { initNavHistory } from './lib/nav-history'
import {
  initParaTarget,
  tryResumePendingPara,
} from './lib/para-anchor'
import { clearSearchHistoryOnLogout } from './lib/search-history'
import { useAuthStore } from './store/auth'
import { clearAllDrafts } from './lib/draft-store'
import { resetPrivacyOnBoot } from './lib/privacy-mask'
import { startVersionCheck } from './lib/version-check'
import { EdgeSwipeBack } from './lib/edge-swipe'

// F113：演示隐私遮罩是“会话内”开关——刷新即重置。模块加载（早于任何
// 组件首渲染）清掉上次会话残留标记，抽屉开关态与 DOM 遮蔽态保持一致。
resetPrivacyOnBoot()

/** PWA Share Target（phase2 M2）：GET /?share=1&url=… 落地后把目标 URL
 * 经 sessionStorage 交给剪藏页（一次性交接，读取即清除）。 */
function handleShareTarget(): void {
  try {
    const params = new URLSearchParams(window.location.search)
    if (params.get('share') !== '1') return
    const shared = params.get('url') ?? params.get('text') ?? ''
    if (shared.startsWith('http://') || shared.startsWith('https://')) {
      sessionStorage.setItem('lumirss-share-url', shared)
      useReaderUi.getState().selectSection('clips')
    }
    params.delete('share')
    params.delete('url')
    params.delete('text')
    params.delete('title')
    const rest = params.toString()
    window.history.replaceState(
      null,
      '',
      window.location.pathname + (rest ? `?${rest}` : ''),
    )
  } catch {
    // share 处理绝不影响应用启动
  }
}
import EntryList from './components/EntryList'
// Bundle guard：对话框非首屏关键路径——懒加载分包（Suspense
// 瞬时 null 无感；与既有 MobileSettingsScreen/一级页 lazy 契约一致）。
import MobileHeader from './components/MobileHeader'
import MobileNavigationDrawer from './components/MobileNavigationDrawer'
import MobileTabBar from './components/MobileTabBar'
import SidebarCollapsedRail from './components/SidebarCollapsedRail'
const ShortcutsHelpDialog = lazy(() => import('./components/ShortcutsHelpDialog'))
const UndoSnackbar = lazy(() => import('./components/UndoSnackbar'))
const SettingsConflictDialog = lazy(() => import('./components/SettingsConflictDialog'))
const VersionUpdateToast = lazy(() => import('./components/VersionUpdateToast'))
const InstallHint = lazy(() => import('./components/InstallHint'))
import Reader from './components/Reader'
import Sidebar from './components/Sidebar'
import { PaneSeparator } from './components/ui/PaneSeparator'
import { Skeleton } from './components/ui/Skeleton'

// Phase K bundle 分割：一级移动页（订阅中心/搜索/收藏）按 tab 首访懒
// 加载——PWA 启动只拉时间线 + Reader 所需代码；桌面切换 section 时
// 同样受益（chunk 局域网/HTTP 缓存下亚秒，Skeleton 占位不闪空）。
const FavoritesPage = lazy(() => import('./components/pages/FavoritesPage'))
const SearchPage = lazy(() => import('./components/pages/SearchPage'))
const SubscriptionsPage = lazy(() => import('./components/pages/SubscriptionsPage'))
// phase2 M1：书签 / 工作区列表页（与 Search 同模式：桌面 Timeline 列位）
const BookmarksPage = lazy(() => import('./components/pages/BookmarksPage'))
const WorkspacesPage = lazy(() => import('./components/pages/WorkspacesPage'))
// phase2 M2：网页剪藏 / 网页快照列表页
const ClipsPage = lazy(() => import('./components/pages/ClipsPage'))
const SnapshotsPage = lazy(() => import('./components/pages/SnapshotsPage'))
// 0021：收件箱（推送式来源的工作台入口）
const InboxPage = lazy(() => import('./components/pages/InboxPage'))
// phase2 G6：Obsidian 只读库
const ObsidianPage = lazy(() => import('./components/pages/ObsidianPage'))
// phase2 G7/G8：Agent 工作台 / 标签与图谱
const AgentWorkbenchPage = lazy(() => import('./components/pages/AgentWorkbenchPage'))
const GraphPage = lazy(() => import('./components/pages/GraphPage'))

function PageSkeleton() {
  return (
    <div className="flex flex-col gap-3 p-4" aria-label="页面加载中">
      {Array.from({ length: 5 }, (_, i) => (
        <Skeleton key={i} className="h-16 w-full" />
      ))}
    </div>
  )
}

/** 分栏约束（Spec §设计规格，借鉴 OrigRead 约束模型） */
const SIDEBAR_MIN = 220
const SIDEBAR_MAX = 300
const TIMELINE_MIN = 360
const TIMELINE_MAX = 460

/** M1 布局契约：全宽 section 桌面独占侧栏外主内容区——Timeline、
 * Reader 与分隔条均不挂载（无文章域查询与空态 DOM）；移动端仍由
 * 上方 section 区承载。其余 section 保持 Sidebar | Timeline | Reader。 */
const FULL_WIDTH_SECTIONS: ReadonlySet<string> = new Set(['agent', 'graph'])

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
  // pool #06：「?」快捷键帮助弹窗（hook 持回调 ref，App 持开关状态）。
  const [shortcutsHelpOpen, setShortcutsHelpOpen] = useState(false)
  // F117：版本轮询（30min fetch /version.json；版本不同 → 更新确认 toast）
  const [newVersion, setNewVersion] = useState<string | null>(null)
  useEffect(
    () =>
      startVersionCheck({
        onNewVersion: (build) => setNewVersion(build),
      }),
    [],
  )
  // 0010 Gate B：全局键盘快捷键（j/k/u/s///?；输入框聚焦时不劫持）
  useKeyboardShortcuts({
    onShowShortcutsHelp: () => setShortcutsHelpOpen(true),
  })
  // P0-01：稍后读不再需要挂载期同步——成员状态由各消费组件的
  // useReadLaterRefs（服务端真源）按需拉取并共享缓存。
  // phase2 M2：PWA Share Target 落地（挂载一次）
  useEffect(handleShareTarget, [])
  // P1.3：统一返回链初始化（必须在 Share Target 之后——replaceState
  // 以净化后的 URL 为基线）。
  useEffect(() => initNavHistory(), [])
  // F015：段落定位链接 —— 启动解析 ?entry=&para=（已登录直接打开；
  // 未登录暂存，登录后重放）。挂载一次。
  useEffect(() => {
    initParaTarget(
      () => useAuthStore.getState().status === 'authenticated',
      (entryRef) => useReaderUi.getState().selectEntry(entryRef),
    )
    // 登录完成后重放暂存目标
    return useAuthStore.subscribe((state) => {
      if (state.status === 'authenticated') {
        tryResumePendingPara((entryRef) => useReaderUi.getState().selectEntry(entryRef))
      }
      // F079：登出/会话过期 → 清理本地搜索历史与暂停标记（幂等）。
      if (state.status === 'unauthenticated') {
        clearSearchHistoryOnLogout()
        clearAllDrafts() // F119：登出清理全部本机草稿
      }
    })
  }, [])

  const settings = useAppSettings((s) => s.settings)
  // P1.3：侧滑/玻璃效果设置（settings 声明之后读取）。
  const swipeBackGesture = settings.swipeBackGesture
  const reduceMotion = settings.reduceMotion
  const glassEffect = settings.glassEffect
  useEffect(() => {
    const root = document.documentElement
    if (glassEffect === 'on') root.dataset.glass = 'on'
    else if (glassEffect === 'off') root.dataset.glass = 'off'
    else root.dataset.glass = 'auto'
  }, [glassEffect])
  const update = useAppSettings((s) => s.update)

  const sidebarCollapsed = settings.sidebarCollapsed
  const timelineCollapsed = settings.timelineCollapsed

  // phase2 修复：移动一级 section 区此前仅靠 lg:hidden 视觉隐藏，DOM 里
  // 始终存在第二份 SearchPage/收藏页实例（live E2E 的 strict mode 抓到
  // 重复文本）。JS 层判定 <1024 才挂载；matchMedia 不可用（jsdom）时
  // 保持原渲染行为。
  const [mobileViewport, setMobileViewport] = useState(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return true
    }
    return window.matchMedia('(max-width: 63.99rem)').matches
  })
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const mq = window.matchMedia('(max-width: 63.99rem)')
    const onChange = () => setMobileViewport(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

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
        {mobileViewport && section !== 'home' && (
          <section
            className={`flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto bg-[var(--lumi-surface)] lg:hidden ${
              selectedEntryRef !== null ? 'max-lg:hidden' : ''
            }`}
            aria-label={
              section === 'subscriptions'
                ? '订阅'
                : section === 'search'
                  ? '搜索'
                  : section === 'bookmarks'
                    ? '书签'
                    : section === 'workspaces'
                      ? '工作区'
                      : section === 'clips'
                        ? '网页剪藏'
                    : section === 'snapshots'
                      ? '网页快照'
                      : section === 'inbox'
                        ? '收件箱'
                        : section === 'obsidian'
                          ? 'Obsidian 库'
                          : section === 'agent'
                            ? 'Agent 工作台'
                            : section === 'graph'
                              ? '标签与图谱'
                              : '收藏'
            }
          >
            {section === 'subscriptions' && (
              <Suspense fallback={<PageSkeleton />}>
                <SubscriptionsPage />
              </Suspense>
            )}
            {section === 'search' && (
              <Suspense fallback={<PageSkeleton />}>
                <SearchPage />
              </Suspense>
            )}
            {section === 'favorites' && (
              <Suspense fallback={<PageSkeleton />}>
                <FavoritesPage />
              </Suspense>
            )}
            {section === 'bookmarks' && (
              <Suspense fallback={<PageSkeleton />}>
                <BookmarksPage />
              </Suspense>
            )}
            {section === 'workspaces' && (
              <Suspense fallback={<PageSkeleton />}>
                <WorkspacesPage />
              </Suspense>
            )}
            {section === 'clips' && (
              <Suspense fallback={<PageSkeleton />}>
                <ClipsPage />
              </Suspense>
            )}
            {section === 'snapshots' && (
              <Suspense fallback={<PageSkeleton />}>
                <SnapshotsPage />
              </Suspense>
            )}
            {section === 'inbox' && (
              <Suspense fallback={<PageSkeleton />}>
                <InboxPage />
              </Suspense>
            )}
            {section === 'obsidian' && (
              <Suspense fallback={<PageSkeleton />}>
                <ObsidianPage />
              </Suspense>
            )}
            {section === 'agent' && (
              <Suspense fallback={<PageSkeleton />}>
                <AgentWorkbenchPage />
              </Suspense>
            )}
            {section === 'graph' && (
              <Suspense fallback={<PageSkeleton />}>
                <GraphPage />
              </Suspense>
            )}
          </section>
        )}

        {/* ===== 全宽页面区（M1 布局契约）：agent / graph 桌面独占主区 =====
            仅 lg 渲染本体（移动端走上方 section 区）；挂载期间下方
            Timeline / 分隔条 / Reader 整体不渲染。 */}
        {FULL_WIDTH_SECTIONS.has(section) && (
          <section
            className="hidden min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-[var(--lumi-surface)] lg:flex"
            aria-label={section === 'agent' ? 'Agent 工作台' : '标签与图谱'}
          >
            <Suspense fallback={<PageSkeleton />}>
              {section === 'agent' ? <AgentWorkbenchPage /> : <GraphPage />}
            </Suspense>
          </section>
        )}

        {/* ===== Timeline（桌面可隐藏，仅 lg 有分隔条；移动端 home section 显示） =====
            0011 阻断修复：桌面栏宽不再用 inline flexBasis（<1024 时 main 为
            flex-col，flexBasis 会把列表高度锁死在 360–460px）——CSS 变量 +
            响应式 flex 类：<1024px w-full + flex-1；≥1024px lg:basis-[宽度]。
            0011 §25/§26：隐藏 = 桌面完全退出布局列（不渲染 section 与分隔
            条，无窄栏）；toggle 移到 Reader 列顶（隐藏时）+ 列表头（可见时）。
            移动端不受 timelineCollapsed 影响（该状态是桌面概念）。 */}
        {/* 全宽 section（agent/graph）不挂载 Timeline 列本体 */}
        {!FULL_WIDTH_SECTIONS.has(section) && (
        <section
          className={`flex min-h-0 min-w-0 w-full flex-1 flex-col overflow-hidden bg-[var(--lumi-surface)] lg:w-auto lg:flex-none lg:basis-[var(--lumi-timeline-width)] ${
            selectedEntryRef === null ? '' : 'hidden lg:flex'
          }${section !== 'home' ? ' max-lg:hidden' : ''}${
            timelineCollapsed ? ' lg:hidden' : ''
          }`}
          style={{ '--lumi-timeline-width': `${settings.timelineWidth}px` } as React.CSSProperties}
        >
          {/* 0022：桌面（lg）搜索 = Timeline 列位；移动端走上方 section 区。
              phase2 M1：书签/工作区列表同模式（桌面 Timeline 列位）。
              hidden 包裹避免移动端双挂载（可见性仍是每视口单一实例）。
              agent/graph 是全宽 section（M1），不进入本三栏分支。 */}
          {section === 'search' ? (
            <div className="hidden min-h-0 flex-1 flex-col lg:flex">
              <Suspense fallback={<PageSkeleton />}>
                <SearchPage />
              </Suspense>
            </div>
          ) : section === 'bookmarks' ? (
            <div className="hidden min-h-0 flex-1 flex-col lg:flex">
              <Suspense fallback={<PageSkeleton />}>
                <BookmarksPage />
              </Suspense>
            </div>
          ) : section === 'workspaces' ? (
            <div className="hidden min-h-0 flex-1 flex-col lg:flex">
              <Suspense fallback={<PageSkeleton />}>
                <WorkspacesPage />
              </Suspense>
            </div>
          ) : section === 'clips' ? (
            <div className="hidden min-h-0 flex-1 flex-col lg:flex">
              <Suspense fallback={<PageSkeleton />}>
                <ClipsPage />
              </Suspense>
            </div>
          ) : section === 'snapshots' ? (
            <div className="hidden min-h-0 flex-1 flex-col lg:flex">
              <Suspense fallback={<PageSkeleton />}>
                <SnapshotsPage />
              </Suspense>
            </div>
          ) : section === 'inbox' ? (
            <div className="hidden min-h-0 flex-1 flex-col lg:flex">
              <Suspense fallback={<PageSkeleton />}>
                <InboxPage />
              </Suspense>
            </div>
          ) : section === 'obsidian' ? (
            <div className="hidden min-h-0 flex-1 flex-col lg:flex">
              <Suspense fallback={<PageSkeleton />}>
                <ObsidianPage />
              </Suspense>
            </div>
          ) : (
            <EntryList />
          )}
        </section>
        )}

        {/* Timeline | Reader 分隔条（未隐藏且未移动端时；全宽 section 无分隔条） */}
        {!timelineCollapsed && !FULL_WIDTH_SECTIONS.has(section) && (
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

        {/* ===== Reader（flex-1 占满剩余；全宽 section 不挂载 =====
            0011 §27：Timeline 隐藏时 toggle 移到 Reader 列顶部左侧
            （同一功能的 toggle，非第二个功能；不产生纵向窄栏）。 */}
        {!FULL_WIDTH_SECTIONS.has(section) && (
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
        )}
      </main>

      {/* Mobile 导航抽屉：仅 <1024 有意义；关闭时不渲染 */}
      <MobileNavigationDrawer />

      {/* P1.3：移动端左缘侧滑返回（渐进增强；无全局 touch-action 改写） */}
      {swipeBackGesture && mobileViewport && (
        <EdgeSwipeBack disabled={reduceMotion} />
      )}

      {/* F20：最近操作撤销条（单实例；无可撤销动作时零渲染） */}
      <Suspense fallback={null}>
        <UndoSnackbar />
      </Suspense>

      {/* 0011 Gate 1：<768 底部导航岛（首页/订阅/搜索/收藏）；Reader 打开时隐藏 */}
      <MobileTabBar />

      {/* Phase M：克制的安装引导（standalone / 已关闭时零渲染）。
          局部 Suspense：lazy 首帧挂起绝不外溢到 root（root 挂起 = 整树
          卸载成 0 字节，mobile-navigation 结构契约即因此破坏）。 */}
      <Suspense fallback={null}>
        <InstallHint />
      </Suspense>

      {/* pool #06：「?」键盘快捷键速查——条件挂载（lazy 只在打开时参与） */}
      {shortcutsHelpOpen && (
        <Suspense fallback={null}>
          <ShortcutsHelpDialog
            open={shortcutsHelpOpen}
            onClose={() => setShortcutsHelpOpen(false)}
          />
        </Suspense>
      )}

      {/* F116：设置冲突解决（settings-sync 409 时触发；无冲突零渲染） */}
      <Suspense fallback={null}>
        <SettingsConflictDialog />
      </Suspense>

      {/* F117：发现新版本确认（稍后/草稿保护；无新版本零渲染） */}
      <Suspense fallback={null}>
        <VersionUpdateToast
          newVersion={newVersion}
          onDismiss={() => setNewVersion(null)}
        />
      </Suspense>
    </div>
  )
}
