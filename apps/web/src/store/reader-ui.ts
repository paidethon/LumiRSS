/** 最小 UI state：view / feed / entry 的当前选择 + 移动端导航抽屉开关。
 * 只放"用户当前点了什么"；feeds/entries/loading/error 等 server state
 * 全部归 TanStack Query，禁止复制到这里。无 persist——刷新后回到
 * All + All Feeds + 无选中，是可接受的默认。 */

import { create } from 'zustand'
import type { EntryView } from '../api/types'

interface ReaderUiState {
  view: EntryView
  selectedFeedUrl: string | null
  selectedEntryRef: string | null
  // 0007：移动端导航抽屉的开关（纯 UI 状态，桌面永不使用）
  mobileSidebarOpen: boolean
  selectView: (view: EntryView) => void
  selectFeed: (feedUrl: string | null) => void
  selectEntry: (entryRef: string | null) => void
  openMobileSidebar: () => void
  closeMobileSidebar: () => void
}

export const useReaderUi = create<ReaderUiState>((set) => ({
  view: 'all',
  selectedFeedUrl: null,
  selectedEntryRef: null,
  mobileSidebarOpen: false,
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
