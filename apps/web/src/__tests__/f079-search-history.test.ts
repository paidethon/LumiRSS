/** F079 搜索历史增强 — 条目结构 {q, filters} 往返、暂停后不记录、
 * 上限 10、登出清理、失效条件剥离、坏 JSON 容错。 */

import {
  clearSearchHistoryOnLogout,
  isHistoryPaused,
  pushSearchHistoryEntry,
  readSearchHistoryEntries,
  setHistoryPaused,
  stripInvalidFilters,
  type SearchHistoryEntry,
} from '../lib/search-history'

function withStorage(fn: () => void): void {
  fn()
}

import { describe, it, expect, beforeEach } from 'vitest'

describe('F079 搜索历史增强', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('F079: 完整条件往返 + 上限 10 + 旧字符串兼容', () => {
    withStorage(() => {
      let items: SearchHistoryEntry[] = []
      items = pushSearchHistoryEntry(items, { q: 'alpha', filters: { feedRef: 'https://a/rss', phrase: 'x' } })
      items = pushSearchHistoryEntry(items, { q: 'beta' })
      // 往返
      expect(readSearchHistoryEntries()[0]).toEqual({ q: 'beta', filters: null })
      expect(readSearchHistoryEntries()[1]).toEqual({
        q: 'alpha',
        filters: { feedRef: 'https://a/rss', phrase: 'x' },
      })
      // 上限 10
      for (let i = 0; i < 15; i++) {
        items = pushSearchHistoryEntry(items, { q: `q${i}` })
      }
      expect(readSearchHistoryEntries().length).toBe(10)
      // 旧字符串结构兼容
      localStorage.setItem('lumirss-search-history', JSON.stringify(['旧字符串搜索']))
      expect(readSearchHistoryEntries()[0]).toEqual({ q: '旧字符串搜索', filters: null })
    })
  })

  it('F079: 暂停后不记录（持久化开关）；登出清理清历史+暂停标记', () => {
    withStorage(() => {
      setHistoryPaused(true)
      expect(isHistoryPaused()).toBe(true)
      let items = pushSearchHistoryEntry([], { q: '被暂停的搜索' })
      expect(items).toEqual([])
      expect(readSearchHistoryEntries()).toEqual([])

      // 恢复记录后可写
      setHistoryPaused(false)
      items = pushSearchHistoryEntry(items, { q: '正常记录' })
      expect(readSearchHistoryEntries().length).toBe(1)

      // 登出清理：历史与暂停标记一起清
      setHistoryPaused(true)
      clearSearchHistoryOnLogout()
      expect(readSearchHistoryEntries()).toEqual([])
      expect(isHistoryPaused()).toBe(false)
      expect(localStorage.getItem('lumirss-search-history')).toBeNull()
    })
  })

  it('F079: 失效条件剥离（feedRef 不在有效集）+ 提示；坏 JSON 容错', () => {
    withStorage(() => {
      const entry: SearchHistoryEntry = {
        q: '历史查询',
        filters: { feedRef: 'https://deleted.example/rss' },
      }
      const valid = new Set(['https://a.example/rss'])
      const stripped = stripInvalidFilters(entry, valid)
      expect(stripped.dropped).toBe(true)
      expect(stripped.entry.filters).toBeNull()
      // 仍有效 → 不剥离
      const kept = stripInvalidFilters(
        { q: '历史查询', filters: { feedRef: 'https://a.example/rss' } },
        valid,
      )
      expect(kept.dropped).toBe(false)
      expect(kept.entry.filters).toEqual({ feedRef: 'https://a.example/rss' })

      // 坏 JSON → 空历史不抛
      localStorage.setItem('lumirss-search-history', '{broken json')
      expect(readSearchHistoryEntries()).toEqual([])
    })
  })
})
