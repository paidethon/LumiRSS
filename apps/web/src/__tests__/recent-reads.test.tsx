/** F10 最近阅读 — lib 纯逻辑（去重/上限/开关/静默失败）+ 面板行为。
 *
 * - recordRecentRead：置顶去重（同 ref 刷新时间）、上限 30、开关关闭
 *   no-op、localStorage 写失败静默（不阻塞打开文章主流程）；
 * - listRecentReads：corrupted JSON → []；
 * - remove/clear；
 * - RecentReads 面板：历史渲染（标题/来源/相对时间）、单条移除、清空、
 *   记录开关、点击条目 selectEntry（不标已读）并关闭面板、空态。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import RecentReads from '../components/RecentReads'
import {
  RECENT_READS_LIMIT,
  clearRecentReads,
  isRecentReadsEnabled,
  listRecentReads,
  recordRecentRead,
  removeRecentRead,
  setRecentReadsEnabled,
} from '../lib/recent-reads'
import { useReaderUi } from '../store/reader-ui'

beforeEach(() => {
  localStorage.clear()
  useReaderUi.setState({ selectedEntryRef: null })
})

afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})

describe('recent-reads lib — 记录/去重/上限', () => {
  it('recordRecentRead：置顶去重（同 ref 移到最前并刷新时间）', () => {
    const t0 = new Date('2026-09-18T08:00:00Z')
    const t1 = new Date('2026-09-18T09:00:00Z')
    recordRecentRead({ entryRef: 'a', feedTitle: '源 A', title: '文章 A' }, t0)
    recordRecentRead({ entryRef: 'b', feedTitle: '源 B', title: '文章 B' }, t0)
    recordRecentRead({ entryRef: 'a', feedTitle: '源 A', title: '文章 A' }, t1)
    const items = listRecentReads()
    expect(items.map((it) => it.entryRef)).toEqual(['a', 'b'])
    expect(items[0]!.openedAt).toBe(t1.toISOString())
    expect(items[0]!.title).toBe('文章 A')
  })

  it(`recordRecentRead：上限 ${RECENT_READS_LIMIT} 条（最旧被截断）`, () => {
    const now = new Date('2026-09-18T08:00:00Z')
    for (let i = 0; i < RECENT_READS_LIMIT + 2; i++) {
      recordRecentRead({ entryRef: `ref-${i}`, feedTitle: '源', title: `文章 ${i}` }, now)
    }
    const items = listRecentReads()
    expect(items).toHaveLength(RECENT_READS_LIMIT)
    expect(items[0]!.entryRef).toBe(`ref-${RECENT_READS_LIMIT + 1}`)
    expect(items.at(-1)!.entryRef).toBe('ref-2')
  })

  it('开关：关闭后不记录；重新开启恢复', () => {
    expect(isRecentReadsEnabled()).toBe(true) // 默认开
    setRecentReadsEnabled(false)
    recordRecentRead({ entryRef: 'a', feedTitle: '源', title: '文章' })
    expect(listRecentReads()).toEqual([])
    setRecentReadsEnabled(true)
    recordRecentRead({ entryRef: 'a', feedTitle: '源', title: '文章' })
    expect(listRecentReads()).toHaveLength(1)
  })

  it('localStorage 写失败（quota）静默不阻塞、读失败返回 []', () => {
    recordRecentRead({ entryRef: 'a', feedTitle: '源', title: '文章' })
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('quota exceeded', 'QuotaExceededError')
    })
    expect(() => recordRecentRead({ entryRef: 'b', feedTitle: '源', title: '文章 B' })).not.toThrow()
    setItemSpy.mockRestore()

    const getItemSpy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('boom')
    })
    expect(listRecentReads()).toEqual([])
    getItemSpy.mockRestore()
  })

  it('corrupted JSON → []；remove/clear 生效', () => {
    localStorage.setItem('lumirss-recent-reads', '{not-json')
    expect(listRecentReads()).toEqual([])
    localStorage.setItem('lumirss-recent-reads', JSON.stringify([{ entryRef: 42 }, 'junk', { entryRef: 'ok', title: 't', openedAt: '2026-09-18T00:00:00Z' }]))
    expect(listRecentReads().map((it) => it.entryRef)).toEqual(['ok'])
    removeRecentRead('ok')
    expect(listRecentReads()).toEqual([])
    recordRecentRead({ entryRef: 'x', feedTitle: '源', title: 'X' })
    clearRecentReads()
    expect(listRecentReads()).toEqual([])
  })
})

describe('RecentReads 面板', () => {
  it('渲染历史（标题/来源/相对时间）；空态诚实', () => {
    recordRecentRead({ entryRef: 'a', feedTitle: '源 A', title: '文章 A' })
    const { unmount } = render(<RecentReads open onClose={vi.fn()} />)
    expect(screen.getByText('文章 A')).toBeInTheDocument()
    expect(screen.getByText('源 A')).toBeInTheDocument()
    expect(screen.getByText('刚刚')).toBeInTheDocument()
    unmount()

    clearRecentReads()
    render(<RecentReads open onClose={vi.fn()} />)
    expect(screen.getByText('还没有阅读记录')).toBeInTheDocument()
  })

  it('点击条目：置顶刷新 + selectEntry（不标已读）+ 关闭面板', () => {
    recordRecentRead({ entryRef: 'a', feedTitle: '源 A', title: '文章 A' })
    recordRecentRead({ entryRef: 'b', feedTitle: '源 B', title: '文章 B' })
    const onClose = vi.fn()
    render(<RecentReads open onClose={onClose} />)
    fireEvent.click(screen.getByText('文章 B'))
    // selectEntry 触发（选择语义，不写已读）
    expect(useReaderUi.getState().selectedEntryRef).toBe('b')
    // LRU：b 被置顶刷新
    expect(listRecentReads()[0]!.entryRef).toBe('b')
    expect(onClose).toHaveBeenCalledTimes(1)
    useReaderUi.getState().selectEntry(null)
  })

  it('单条移除与清空', () => {
    recordRecentRead({ entryRef: 'a', feedTitle: '源 A', title: '文章 A' })
    recordRecentRead({ entryRef: 'b', feedTitle: '源 B', title: '文章 B' })
    render(<RecentReads open onClose={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: '移除「文章 A」' }))
    expect(screen.queryByText('文章 A')).toBeNull()
    expect(listRecentReads().map((it) => it.entryRef)).toEqual(['b'])
    fireEvent.click(screen.getByRole('button', { name: '清空最近阅读' }))
    expect(screen.getByText('还没有阅读记录')).toBeInTheDocument()
    expect(listRecentReads()).toEqual([])
  })

  it('记录开关：切换写 localStorage；关闭后面板提示不再新增', () => {
    recordRecentRead({ entryRef: 'a', feedTitle: '源 A', title: '文章 A' })
    render(<RecentReads open onClose={vi.fn()} />)
    const toggle = screen.getByTestId('recent-reads-toggle')
    expect(toggle.getAttribute('aria-checked')).toBe('true')
    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-checked')).toBe('false')
    expect(localStorage.getItem('lumirss-recent-reads-enabled')).toBe('0')
    expect(isRecentReadsEnabled()).toBe(false)
    expect(screen.getByText('记录已关闭：现有历史保留，但不再新增。')).toBeInTheDocument()
    // 再打开恢复
    fireEvent.click(toggle)
    expect(localStorage.getItem('lumirss-recent-reads-enabled')).toBe('1')
  })

  it('关闭（open=false）零渲染；Escape 关闭回调', () => {
    const onClose = vi.fn()
    const { rerender, container } = render(<RecentReads open={false} onClose={onClose} />)
    expect(container.querySelector('[data-testid="recent-reads-panel"]')).toBeNull()
    rerender(<RecentReads open onClose={onClose} />)
    expect(screen.getByTestId('recent-reads-panel')).toBeInTheDocument()
    fireEvent(window, new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    return waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
  })
})

describe('记录点接线 — EntryCard 行点击记录最近阅读', () => {
  it('普通点击 = 记录 + selectEntry；开关关闭 = 只 selectEntry 不记录', async () => {
    const QueryClient = (await import('@tanstack/react-query')).QueryClient
    const QueryClientProvider = (await import('@tanstack/react-query')).QueryClientProvider
    const { default: EntryCard } = await import('../components/EntryCard')
    const item = {
      entryRef: 'e9.x',
      title: '被打开的文章',
      feedTitle: '来源 Z',
      author: null,
      url: null,
      publishedAt: '2026-09-18T08:00:00Z',
      read: false,
      starred: false,
    }
    function renderCard() {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
      return render(
        <QueryClientProvider client={client}>
          <EntryCard item={item} selected={false} />
        </QueryClientProvider>,
      )
    }
    // 开关默认开：点击记录
    const first = renderCard()
    fireEvent.click(screen.getByRole('button', { name: '被打开的文章' }))
    expect(useReaderUi.getState().selectedEntryRef).toBe('e9.x')
    expect(listRecentReads().map((it) => it.entryRef)).toEqual(['e9.x'])
    first.unmount()
    useReaderUi.getState().selectEntry(null)

    // 开关关闭：点击仍打开文章，但不记录
    clearRecentReads()
    setRecentReadsEnabled(false)
    const second = renderCard()
    fireEvent.click(screen.getByRole('button', { name: '被打开的文章' }))
    expect(useReaderUi.getState().selectedEntryRef).toBe('e9.x')
    expect(listRecentReads()).toEqual([])
    second.unmount()
    setRecentReadsEnabled(true)
  })
})
