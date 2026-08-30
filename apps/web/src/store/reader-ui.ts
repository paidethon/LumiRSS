/** 最小 UI state：section / view / feed / entry 的当前选择 + 移动端导航抽屉开关。
 * 只放"用户当前点了什么"；feeds/entries/loading/error 等 server state
 * 全部归 TanStack Query，禁止复制到这里。无 persist——刷新后回到
 * Home + All + All Feeds + 无选中，是可接受的默认。 */

import { create } from 'zustand'
import type { EntryView } from '../api/types'

/** 一级页面（0011 Spec §设计规格）：与 EntryView 正交。
 *
 * EntryView（all/unread/starred）描述"文章列表按什么过滤"；
 * AppSection 描述"用户在哪个一级页面"。收藏页内部复用
 * view='starred' 查询，不复制数据。 */
export type AppSection = 'home' | 'subscriptions' | 'search' | 'favorites'

interface ReaderUiState {
  section: AppSection
  view: EntryView
  selectedFeedUrl: string | null
  selectedEntryRef: string | null
  // 0007：移动端导航抽屉的开关（纯 UI 状态，桌面永不使用）
  mobileSidebarOpen: boolean
  selectSection: (section: AppSection) => void
  selectView: (view: EntryView) => void
  selectFeed: (feedUrl: string | null) => void
  selectEntry: (entryRef: string | null) => void
  openMobileSidebar: () => void
  closeMobileSidebar: () => void
}

export const useReaderUi = create<ReaderUiState>((set) => ({
  section: 'home',
  view: 'all',
  selectedFeedUrl: null,
  selectedEntryRef: null,
  mobileSidebarOpen: false,
  // 切 section 不清空 home 的 view/feed 筛选——返回首页时恢复原状态
  //（收藏页语义由 favorites 自身携带，不污染 home 的 view）。
  selectSection: (section) =>
    set((state) =>
      state.section === section
        ? state
        : { section, selectedEntryRef: null },
    ),
  // 切 view / feed 时清空 selection：旧选择可能已不属于新列表。
  selectView: (view) =>
    set((state) =>
      state.view === view ? state : { view, selectedEntryRef: null },
    ),
  selectFeed: (feedUrl) =>
    set((state) =>
      state.selectedFeedUrl === feedUrl
        ? state
        : { selectedFeedUrl: feedUrl, selectedEntryRef: null },
    ),
  selectEntry: (entryRef) => set({ selectedEntryRef: entryRef }),
  openMobileSidebar: () => set({ mobileSidebarOpen: true }),
  closeMobileSidebar: () => set({ mobileSidebarOpen: false }),
}))
