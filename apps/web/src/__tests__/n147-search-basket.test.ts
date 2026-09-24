/** N147 搜索结果暂存篮 — 设备本地篮（localStorage）回归。
 *
 * - 加入/去重（同 entryRef 只留一条）/ 上限 100（诚实计数溢出）；
 * - localStorage 持久化（跨「页面」往返）；
 * - 登出清理（resetAccountState → 篮与 localStorage 全清）；
 * - 导出 markdown（标题/来源/日期/链接；空篮诚实输出）。
 */

import { beforeEach, describe, expect, it } from 'vitest'
import { QueryClient } from '@tanstack/react-query'
import { resetAccountState } from '../lib/auth-reset'
import {
  SEARCH_BASKET_LIMIT,
  addBasketItems,
  basketToMarkdown,
  readBasketItems,
  removeBasketItem,
  useSearchBasket,
  type SearchBasketItem,
} from '../store/search-basket'

function makeItem(entryRef: string, title = `标题 ${entryRef}`): Omit<SearchBasketItem, 'addedAt'> {
  return {
    entryRef,
    title,
    feedTitle: '源A',
    publishedAt: '2026-09-23T08:00:00Z',
    url: `https://example.com/${entryRef}`,
  }
}

beforeEach(() => {
  localStorage.clear()
  useSearchBasket.getState().reset()
})

describe('N147 暂存篮：加入 / 去重 / 上限', () => {
  it('加入并按 entryRef 去重（重复计数诚实）', () => {
    const first = addBasketItems([], [makeItem('a'), makeItem('b')])
    expect(first.added).toBe(2)
    expect(first.duplicated).toBe(0)
    const second = addBasketItems(first.basket, [makeItem('b'), makeItem('c')])
    expect(second.added).toBe(1)
    expect(second.duplicated).toBe(1)
    expect(second.basket.map((i) => i.entryRef)).toEqual(['a', 'b', 'c'])
  })

  it('上限 100：溢出不加入并诚实计数', () => {
    let basket: SearchBasketItem[] = []
    for (let i = 0; i < SEARCH_BASKET_LIMIT; i++) {
      basket = addBasketItems(basket, [makeItem(`ref-${i}`)]).basket
    }
    expect(basket.length).toBe(SEARCH_BASKET_LIMIT)
    const overflow = addBasketItems(basket, [makeItem('ref-new'), makeItem('ref-1')])
    expect(overflow.added).toBe(0)
    expect(overflow.duplicated).toBe(1)
    expect(overflow.droppedOverCap).toBe(1)
    expect(overflow.basket.length).toBe(SEARCH_BASKET_LIMIT)
  })

  it('移除为 set 语义（不存在也安全）', () => {
    const report = addBasketItems([], [makeItem('a'), makeItem('b')])
    const next = removeBasketItem(report.basket, 'a')
    expect(next.map((i) => i.entryRef)).toEqual(['b'])
    expect(removeBasketItem(next, 'nope').length).toBe(1)
  })
})

describe('N147 暂存篮：持久化与登出清理', () => {
  it('store.addMany 写穿 localStorage；load 往返（跨页面保留）', () => {
    const store = useSearchBasket.getState()
    store.addMany([makeItem('persist-1'), makeItem('persist-2')])
    // 新「页面」：直接读 localStorage。
    expect(readBasketItems().map((i) => i.entryRef)).toEqual(['persist-1', 'persist-2'])
    // 同一 store reset 后 load 也能恢复（模拟刷新后的重载路径）。
    useSearchBasket.getState().reset()
    expect(useSearchBasket.getState().items).toEqual([])
    useSearchBasket.getState().load()
    expect(useSearchBasket.getState().items.map((i) => i.entryRef)).toEqual([
      'persist-1',
      'persist-2',
    ])
  })

  it('登出（resetAccountState）清空篮与 localStorage', () => {
    useSearchBasket.getState().addMany([makeItem('a-secret')])
    expect(localStorage.getItem('lumirss-search-basket')).not.toBeNull()
    resetAccountState(new QueryClient())
    expect(useSearchBasket.getState().items).toEqual([])
    expect(localStorage.getItem('lumirss-search-basket')).toBeNull()
  })

  it('坏 JSON / 异形数据容错', () => {
    localStorage.setItem('lumirss-search-basket', '{not json')
    expect(readBasketItems()).toEqual([])
    localStorage.setItem(
      'lumirss-search-basket',
      JSON.stringify([{ entryRef: 'ok' }, { nope: true }, 'junk', { entryRef: 'ok' }]),
    )
    expect(readBasketItems().map((i) => i.entryRef)).toEqual(['ok'])
  })
})

describe('N147 暂存篮：markdown 导出', () => {
  it('标题/来源/日期/链接清单；空篮诚实输出', () => {
    const md = basketToMarkdown([
      {
        entryRef: 'e1',
        title: 'Rust 发布',
        feedTitle: '源A',
        publishedAt: '2026-09-23T08:00:00Z',
        url: 'https://example.com/1',
        addedAt: '2026-09-23T09:00:00Z',
      },
      {
        entryRef: 'e2',
        title: '',
        feedTitle: '',
        publishedAt: '',
        url: null,
        addedAt: '',
      },
    ])
    expect(md).toContain('- Rust 发布')
    expect(md).toContain('源A · 2026-09-23')
    expect(md).toContain('https://example.com/1')
    expect(md).toContain('- e2') // 无标题回退 ref
    expect(basketToMarkdown([])).toContain('（空）')
  })
})
