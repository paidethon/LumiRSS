/** 会话级搜索状态（P1.3 统一返回链，2026-09 移动端专项）。
 *
 * 搜索词与筛选此前是 SearchPage 本地 state——离开页面即丢，浏览器
 * 返回也恢复不了。提升到会话 store 后：
 * - 返回链（浏览器后退/侧滑/返回按钮）能恢复搜索词与筛选；
 * - 桌面/移动两个挂载点共享同一状态（同 section 单实例，不冲突）。
 * 会话语义：不持久化，刷新回空。 */

import { create } from 'zustand'

export type SearchViewFilter = 'all' | 'unread' | 'starred'

export interface SearchState {
  q: string
  submitted: string
  view: SearchViewFilter
  categoryKey: string
  setQ: (q: string) => void
  setSubmitted: (submitted: string) => void
  setView: (view: SearchViewFilter) => void
  setCategoryKey: (categoryKey: string) => void
  /** 应用保存的搜索视图（query + 筛选一次性恢复）。 */
  apply: (snapshot: { q: string; submitted: string; view: SearchViewFilter; categoryKey: string }) => void
  clear: () => void
}

export const useSearchState = create<SearchState>((set) => ({
  q: '',
  submitted: '',
  view: 'all',
  categoryKey: '',
  setQ: (q) => set({ q }),
  setSubmitted: (submitted) => set({ submitted }),
  setView: (view) => set({ view }),
  setCategoryKey: (categoryKey) => set({ categoryKey }),
  apply: (snapshot) => set(snapshot),
  clear: () => set({ q: '', submitted: '', view: 'all', categoryKey: '' }),
}))
