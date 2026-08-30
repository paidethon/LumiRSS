/** 最小 UI state：section / scope / view / entry 的当前选择 + 移动端导航抽屉开关。
 * 只放"用户当前点了什么"；feeds/entries/loading/error 等 server state
 * 全部归 TanStack Query，禁止复制到这里。无 persist——刷新后回到
 * Home + All + 全部信息源 + 无选中，是可接受的默认。
 *
 * 0011：selectedFeedUrl（boolean soup 成员）→ ContentScope 判别联合
 * （lib/navigation.ts，§15/§16）。Layout 展开状态（RSS tree、分类展开、
 * 折叠）不在这里——它们属于组件本地 layout state（§17），与导航正交。 */

import { create } from 'zustand'
import type { UiView } from '../lib/read-later'
import type { ContentScope } from '../lib/navigation'

/** 一级页面（0011 Spec §设计规格）：与视图/内容范围语义正交。 */
export type AppSection = 'home' | 'subscriptions' | 'search' | 'favorites'

export const ALL_SCOPE: ContentScope = { kind: 'all' }

interface ReaderUiState {
  section: AppSection
  scope: ContentScope
  view: UiView
  selectedEntryRef: string | null
  // 0007：移动端导航抽屉的开关（纯 UI 状态，桌面永不使用）
  mobileSidebarOpen: boolean
  selectSection: (section: AppSection) => void
  selectScope: (scope: ContentScope) => void
  selectView: (view: UiView) => void
  selectEntry: (entryRef: string | null) => void
  openMobileSidebar: () => void
  closeMobileSidebar: () => void
}

/** 结构相等：判别联合逐字段比较（幂等 no-op 判定）。 */
function scopeEquals(a: ContentScope, b: ContentScope): boolean {
  if (a.kind !== b.kind) return false
  if (a.kind === 'rss-category' && b.kind === 'rss-category') {
    return a.categoryId === b.categoryId
  }
  if (a.kind === 'rss-feed' && b.kind === 'rss-feed') {
    return a.feedUrl === b.feedUrl
  }
  return true
}

export const useReaderUi = create<ReaderUiState>((set) => ({
  section: 'home',
  scope: ALL_SCOPE,
  view: 'all',
  selectedEntryRef: null,
  mobileSidebarOpen: false,
  // 切 section 不清空 home 的筛选——返回首页时恢复原状态。
  selectSection: (section) =>
    set((state) =>
      state.section === section
        ? state
        : { section, selectedEntryRef: null },
    ),
  // 切 scope 清空 selection：旧选择可能已不属于新列表。
  // 幂等判定用结构相等（调用方每次传新字面量，不能只比引用）。
  selectScope: (scope) =>
    set((state) =>
      scopeEquals(state.scope, scope)
        ? state
        : { scope, selectedEntryRef: null },
    ),
  // 工作区切换（稍后读/收藏）复用 view；切 view 时清 selection。
  selectView: (view) =>
    set((state) =>
      state.view === view ? state : { view, selectedEntryRef: null },
    ),
  selectEntry: (entryRef) => set({ selectedEntryRef: entryRef }),
  openMobileSidebar: () => set({ mobileSidebarOpen: true }),
  closeMobileSidebar: () => set({ mobileSidebarOpen: false }),
}))
