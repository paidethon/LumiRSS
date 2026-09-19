/** P1.3 统一返回链（2026-09 移动端专项）。
 *
 * 现状是 Zustand 纯内存导航：浏览器后退/侧滑离开应用而非返回上一处。
 * 本模块为现有状态导航建立最小统一历史层（不引入路由库、不双轨）：
 *
 * - 每次 section/scope/view/selection 导航 push 一条 history 记录
 *   （相同状态的重复导航不 push）；
 * - popstate → 恢复快照（section/订阅范围/视图/选中文章 + 搜索状态由
 *   search-state store 承载，一并恢复）；
 * - 顶部返回按钮 / 移动端侧滑 / 浏览器后退调用同一 goBack() 语义；
 * - 浮层（抽屉/灯箱等）按明确层级参与历史：一次后退只关一层，不同时
 *   关闭三层并跳离页面；
 * - 深度守卫：没有可返回的应用页面时不执行 back（不把用户带离应用、
 *   不循环 push 虚假历史）；
 * - 前进同样恢复（popstate 双向触发）。
 */

import { useReaderUi } from '../store/reader-ui'
import type { AppSection } from '../store/reader-ui'
import type { ContentScope } from './navigation'

const HISTORY_KEY = 'lumi'

export interface NavSnapshot {
  section: AppSection
  scope: ContentScope
  view: string
  selectedEntryRef: string | null
}

interface HistoryEntryState {
  [HISTORY_KEY]?: NavSnapshot
  lumiDepth?: number
  overlayId?: string
}

/** 我们 push 的应用历史条数（0 = 根，无应用内可返回页）。 */
let depth = 0
/** 影子栈：与 history 条目一一对应的快照。history API 读不到「上一条
 * 的 state」，goBack() 需要它做同步恢复（jsdom 的 back() 不派发
 * popstate；真实浏览器 popstate 稍后到达 → sameNav 幂等跳过）。 */
const navStack: NavSnapshot[] = []
/** 恢复快照期间抑制 push（popstate 引起的 setState 不产生新历史）。 */
let suppressPush = false
/** 浮层栈：按打开顺序登记，后退只关最上层。 */
const overlayStack: Array<{ id: string; close: () => void }> = []

function scopeEquals(a: ContentScope, b: ContentScope): boolean {
  if (a.kind !== b.kind) return false
  if (a.kind === 'rss-category' && b.kind === 'rss-category') return a.categoryId === b.categoryId
  if (a.kind === 'rss-feed' && b.kind === 'rss-feed') return a.feedUrl === b.feedUrl
  return true
}

function snapshot(): NavSnapshot {
  const s = useReaderUi.getState()
  return {
    section: s.section,
    scope: s.scope,
    view: s.view,
    selectedEntryRef: s.selectedEntryRef,
  }
}

function sameNav(a: NavSnapshot, b: NavSnapshot): boolean {
  return (
    a.section === b.section &&
    a.view === b.view &&
    a.selectedEntryRef === b.selectedEntryRef &&
    scopeEquals(a.scope, b.scope)
  )
}

function closeOverlays(): void {
  while (overlayStack.length > 0) {
    overlayStack.pop()?.close()
  }
}

/** 把快照应用到导航 store（popstate 与 goBack 共用；抑制 push）。 */
function applySnapshot(target: NavSnapshot): void {
  const current = snapshot()
  if (sameNav(target, current)) return
  suppressPush = true
  try {
    useReaderUi.setState({
      section: target.section,
      scope: target.scope,
      view: target.view as never,
      selectedEntryRef: target.selectedEntryRef,
      mobileSidebarOpen: false,
    })
  } finally {
    suppressPush = false
  }
}

/** App 挂载时调用一次；返回清理函数。jsdom/SSR 安全。 */
export function initNavHistory(): () => void {
  if (typeof window === 'undefined' || typeof window.history === 'undefined') return () => {}
  depth = 0
  navStack.length = 0
  navStack.push(snapshot())
  try {
    window.history.replaceState(
      { [HISTORY_KEY]: navStack[0], lumiDepth: 0 },
      '',
      window.location.pathname + window.location.search,
    )
  } catch {
    /* 状态序列化失败（极端）→ 跳过初始化，导航仍可用 */
  }
  const onPopState = (event: PopStateEvent) => {
    const state = event.state as HistoryEntryState | null
    if (state === null || !(HISTORY_KEY in state)) return
    depth = typeof state.lumiDepth === 'number' ? state.lumiDepth : 0
    const target = state[HISTORY_KEY]
    if (target === undefined) return
    // 前进/后退到浮层条目：浮层按层级由各自 open/close 管理；
    // 到达非浮层条目时清空残存浮层（离开页面语义）。
    if (state.overlayId === undefined) closeOverlays()
    applySnapshot(target)
  }
  window.addEventListener('popstate', onPopState)
  return () => window.removeEventListener('popstate', onPopState)
}

/** 导航动作后调用：与当前 history 状态相同则不 push（幂等）。 */
export function pushNavHistory(): void {
  if (suppressPush) return
  if (typeof window === 'undefined' || typeof window.history === 'undefined') return
  const snap = snapshot()
  const current = window.history.state as HistoryEntryState | null
  if (current !== null && current[HISTORY_KEY] !== undefined && sameNav(current[HISTORY_KEY]!, snap)) {
    return
  }
  depth += 1
  // 截断前进分支（新导航使 forward 历史失效），影子栈与 history 对齐。
  navStack.length = depth
  navStack[depth] = snap
  try {
    window.history.pushState({ [HISTORY_KEY]: snap, lumiDepth: depth }, '')
  } catch {
    depth -= 1
    navStack.length = depth + 1
  }
}

/** 浮层打开：登记关闭回调并 push 一条浮层历史（后退只关这层）。 */
export function registerOverlay(id: string, close: () => void): void {
  overlayStack.push({ id, close })
  if (typeof window === 'undefined' || typeof window.history === 'undefined') return
  depth += 1
  try {
    window.history.pushState({ [HISTORY_KEY]: snapshot(), lumiDepth: depth, overlayId: id }, '')
  } catch {
    depth -= 1
  }
}

/** 浮层关闭（UI/Escape 触发）：消耗它自己的历史条目。 */
export function unregisterOverlay(id: string): void {
  const index = overlayStack.findIndex((entry) => entry.id === id)
  if (index === -1) return
  overlayStack.splice(index, 1)
  if (typeof window === 'undefined' || typeof window.history === 'undefined') return
  const state = window.history.state as HistoryEntryState | null
  if (state !== null && state.overlayId === id) {
    window.history.back() // popstate 到浮层前状态（nav 相同 → no-op 恢复）
  }
}

/** 是否存在浮层（返回按钮优先关浮层）。 */
export function hasOverlays(): boolean {
  return overlayStack.length > 0
}

/** 有没有应用内可返回的页面（深度守卫：根页面不执行 back）。 */
export function canGoBack(): boolean {
  return depth > 0 || overlayStack.length > 0
}

/** 统一返回语义：顶部返回按钮 / 侧滑 / 之外的程序化返回都走这里。
 * 同步恢复上一快照（即时反馈；真实浏览器 popstate 到达后 sameNav
 * 幂等跳过，jsdom 无 popstate 也已生效）。返回 false = 应用根。 */
export function goBack(): boolean {
  if (overlayStack.length > 0) {
    // 只关最上层浮层（其 close → unregisterOverlay 消耗历史条目）。
    overlayStack[overlayStack.length - 1]?.close()
    return true
  }
  if (depth <= 0) return false
  const target = navStack[depth - 1]
  depth -= 1
  navStack.length = depth + 1
  if (target !== undefined) applySnapshot(target)
  window.history.back()
  return true
}
