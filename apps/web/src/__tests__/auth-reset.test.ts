/** auth-reset — O157 换账号防串号的统一重置测试。
 *
 * 核心场景：A 账号留下完整本地足迹（Query 缓存、UI 选择、草稿、
 * 搜索历史、最近阅读、阅读位置、待同步设置 dirty 键）→
 * resetAccountState → 断言全部清空，B 登录后看不到 A 的任何数据。
 * 设备偏好（主题等 lumirss-settings）保留。
 */

import { beforeEach, describe, expect, it } from 'vitest'
import { QueryClient } from '@tanstack/react-query'
import { resetAccountState } from '../lib/auth-reset'
import { flushDraftForTests } from '../lib/draft-store'
import { listRecentReads, recordRecentRead } from '../lib/recent-reads'
import { loadReadingPosition, saveReadingPosition } from '../lib/reading-position'
import { useReaderUi } from '../store/reader-ui'
import { useSearchState } from '../store/search-state'
import { useUndo } from '../store/undo'
import { useAppSettings } from '../store/app-settings'

const A_ENTRY_REF = 'b2ZmZXItYQ==' // A 账号读过的文章 ref（测试假值）

/** 复刻 search-history 的存储约定（pushSearchHistoryEntry 的底层 key）。 */
function seedSearchHistory(): void {
  localStorage.setItem(
    'lumirss-search-history',
    JSON.stringify([{ q: 'A 的秘密搜索词', at: '2026-09-01T00:00:00Z', filters: null }]),
  )
}

async function seedQueryCache(queryClient: QueryClient): Promise<void> {
  queryClient.setQueryData(['feeds'], [{ feedUrl: 'https://a.example/rss', title: 'A 的订阅' }])
  queryClient.setQueryData(['entries', A_ENTRY_REF], { title: 'A 的文章' })
  // 确认缓存里真的有数据（前置成立，断言才有意义）
  expect(queryClient.getQueryData(['feeds'])).not.toBeUndefined()
}

beforeEach(() => {
  localStorage.clear()
  useReaderUi.setState({
    section: 'search',
    scope: { kind: 'rss-feed', feedUrl: 'https://a.example/rss' },
    view: 'starred',
    selectedEntryRef: A_ENTRY_REF,
    mobileSidebarOpen: true,
  })
  useSearchState.setState({ q: 'A 的搜索', submitted: 'A 的搜索', view: 'unread', categoryKey: 'cat-a' })
  useUndo.setState({ current: null })
})

describe('resetAccountState（换账号防串号）', () => {
  it('A 的全部状态 → reset → 查询缓存与本地足迹清空，不出现 A 的数据', async () => {
    const queryClient = new QueryClient()
    await seedQueryCache(queryClient)

    // 草稿（白名单 formId；flush 绕过 debounce 直接落盘）
    flushDraftForTests('note-editor', { body: 'A 的草稿内容' })
    expect(localStorage.getItem('lumirss-draft-note-editor')).not.toBeNull()

    // 搜索历史 / 最近阅读 / 阅读位置
    seedSearchHistory()
    recordRecentRead({ entryRef: A_ENTRY_REF, feedTitle: 'A 的源', title: 'A 的文章' })
    saveReadingPosition(A_ENTRY_REF, { ratio: 0.5, anchorText: null, savedAt: '2026-09-01T00:00:00Z' })
    expect(listRecentReads()).toHaveLength(1)
    expect(loadReadingPosition(A_ENTRY_REF)).not.toBeNull()

    // 待撤销动作（闭包可能引用 A 的数据）
    useUndo.getState().push({
      label: '已标记已读',
      undo: async () => {},
      check: async () => true,
    })

    resetAccountState(queryClient)

    // 查询缓存：A 的 feeds/entries 全部作废
    expect(queryClient.getQueryData(['feeds'])).toBeUndefined()
    expect(queryClient.getQueryData(['entries', A_ENTRY_REF])).toBeUndefined()
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0)

    // UI 选择状态回启动默认
    expect(useReaderUi.getState().section).toBe('home')
    expect(useReaderUi.getState().scope).toEqual({ kind: 'all' })
    expect(useReaderUi.getState().view).toBe('all')
    expect(useReaderUi.getState().selectedEntryRef).toBeNull()
    expect(useReaderUi.getState().mobileSidebarOpen).toBe(false)

    // 会话级搜索 / 撤销槽
    expect(useSearchState.getState().q).toBe('')
    expect(useSearchState.getState().submitted).toBe('')
    expect(useUndo.getState().current).toBeNull()

    // 本机足迹：草稿 / 搜索历史 / 最近阅读 / 阅读位置
    expect(localStorage.getItem('lumirss-draft-note-editor')).toBeNull()
    expect(localStorage.getItem('lumirss-search-history')).toBeNull()
    expect(listRecentReads()).toHaveLength(0)
    expect(loadReadingPosition(A_ENTRY_REF)).toBeNull()
  })

  it('登出后再登录（二次 reset）幂等，无异常', async () => {
    const queryClient = new QueryClient()
    resetAccountState(queryClient)
    recordRecentRead({ entryRef: A_ENTRY_REF, title: 'A 的文章' })
    resetAccountState(queryClient)
    expect(listRecentReads()).toHaveLength(0)
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0)
  })

  it('保留设备偏好：主题等 lumirss-settings 不被清除', () => {
    const queryClient = new QueryClient()
    const themeMode = useAppSettings.getState().settings.themeMode
    localStorage.setItem('lumirss-settings', JSON.stringify({ themeMode: 'dark' }))
    resetAccountState(queryClient)
    expect(localStorage.getItem('lumirss-settings')).not.toBeNull()
    // store 的设置对象不受 reset 影响（设备偏好非账号数据）
    expect(useAppSettings.getState().settings.themeMode).toBe(themeMode)
  })
})
