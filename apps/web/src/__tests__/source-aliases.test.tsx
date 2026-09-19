/** R03 来源显示别名测试 — 存储（设置/清除/持久/上限）+ 设置 UI。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  clearSourceAlias,
  getSourceAliases,
  resolveSourceAlias,
  setSourceAlias,
  SOURCE_ALIAS_LIMIT,
} from '../lib/source-aliases'
import SourceAliasSettings from '../components/SourceAliasSettings'

const STORAGE_KEY = 'lumirss-source-aliases'

/** useFeeds mock（组件与侧栏共用同一 hook）；用可变变量按用例切换状态。 */
let feedsState: { titles: string[] | null; isError: boolean } = { titles: [], isError: false }

vi.mock('../api/queries', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/queries')>()
  return {
    ...actual,
    useFeeds: () => ({
      data:
        feedsState.titles === null
          ? undefined
          : feedsState.titles.map((t) => ({ title: t, feedUrl: `https://f.example/${encodeURIComponent(t)}` })),
      isPending: false,
      isLoading: false,
      isError: feedsState.isError,
      refetch: vi.fn(),
    }),
  }
})

function renderSettings() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <SourceAliasSettings />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  feedsState = { titles: [], isError: false }
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('source-aliases 纯函数', () => {
  it('设置后 resolveSourceAlias 返回别名；未设置返回真实名', () => {
    expect(resolveSourceAlias('Hacker News')).toBe('Hacker News')
    setSourceAlias('Hacker News', '黑客快讯')
    expect(resolveSourceAlias('Hacker News')).toBe('黑客快讯')
    expect(resolveSourceAlias('其它来源')).toBe('其它来源')
    expect(resolveSourceAlias('')).toBe('')
  })

  it('清除后恢复真实名；清除不存在的别名不抛错', () => {
    setSourceAlias('源A', '别名A')
    expect(localStorage.getItem(STORAGE_KEY)).toBe('{"源A":"别名A"}')
    clearSourceAlias('源A')
    expect(resolveSourceAlias('源A')).toBe('源A')
    expect(getSourceAliases().size).toBe(0)
    expect(() => clearSourceAlias('从未设置')).not.toThrow()
  })

  it('持久化：重新读取（模拟刷新）别名仍在；空串别名 = 清除语义', () => {
    setSourceAlias('源B', '别名B')
    const raw = localStorage.getItem(STORAGE_KEY)
    expect(raw).not.toBeNull()
    // 模块无内存缓存，存储即真相 → 重读即「刷新后」
    expect(resolveSourceAlias('源B')).toBe('别名B')
    setSourceAlias('源B', '   ')
    expect(resolveSourceAlias('源B')).toBe('源B')
  })

  it('别名不修改真实名：只写独立 key，其它 localStorage 不受影响', () => {
    localStorage.setItem('lumirss-settings', '{"theme":"dark"}')
    setSourceAlias('Tech Daily', '科技日报')
    expect(JSON.parse(localStorage.getItem('lumirss-settings')!)).toEqual({ theme: 'dark' })
    expect(getSourceAliases().get('Tech Daily')).toBe('科技日报')
    // 「真实名」来自 FreshRSS/API —— 本模块没有任何触碰它的途径
    expect(Object.keys(JSON.parse(localStorage.getItem(STORAGE_KEY)!))).toEqual(['Tech Daily'])
  })

  it(`上限 ${SOURCE_ALIAS_LIMIT} 条：超出淘汰最早写入`, () => {
    for (let i = 0; i < SOURCE_ALIAS_LIMIT + 5; i += 1) {
      setSourceAlias(`feed-${String(i).padStart(3, '0')}`, `alias-${i}`)
    }
    const map = getSourceAliases()
    expect(map.size).toBe(SOURCE_ALIAS_LIMIT)
    expect(map.has('feed-000')).toBe(false) // 最早的被淘汰（205 条写入淘汰 5 条）
    expect(map.has('feed-004')).toBe(false)
    expect(map.has('feed-005')).toBe(true)
    expect(resolveSourceAlias(`feed-${String(SOURCE_ALIAS_LIMIT + 4).padStart(3, '0')}`)).toBe(
      `alias-${SOURCE_ALIAS_LIMIT + 4}`,
    )
  })

  it('损坏 JSON → 空 Map 不抛错', () => {
    localStorage.setItem(STORAGE_KEY, '{broken')
    expect(getSourceAliases().size).toBe(0)
    localStorage.setItem(STORAGE_KEY, '["not-an-object"]')
    expect(getSourceAliases().size).toBe(0)
  })
})

describe('SourceAliasSettings UI', () => {
  it('订阅列表逐行显示真实名 + 别名输入 + 保存/清除', async () => {
    feedsState = { titles: ['Alpha Blog', 'Beta News'], isError: false }
    const { within } = await import('@testing-library/react')
    renderSettings()
    expect(screen.getByText('Alpha Blog')).toBeInTheDocument()
    expect(screen.getByText('Beta News')).toBeInTheDocument()
    expect(screen.getAllByText('未设置别名')).toHaveLength(2)

    // 限定在 Alpha 行内操作（每行都有同名按钮，全局查询会有歧义）
    const alphaRow = screen.getByText('Alpha Blog').closest('li') as HTMLElement
    fireEvent.change(within(alphaRow).getByLabelText('Alpha Blog 的别名'), {
      target: { value: '阿尔法' },
    })
    fireEvent.click(within(alphaRow).getByRole('button', { name: '保存' }))
    await waitFor(() => {
      expect(within(alphaRow).getByText('当前别名：阿尔法')).toBeInTheDocument()
    })
    expect(resolveSourceAlias('Alpha Blog')).toBe('阿尔法')
    // 未编辑的 Beta 行不受影响
    expect(screen.getByText('Beta News').closest('li')).toHaveTextContent('未设置别名')

    // 清除 → 恢复真实名
    fireEvent.click(within(alphaRow).getByRole('button', { name: '清除' }))
    await waitFor(() => {
      expect(within(alphaRow).getByText('未设置别名')).toBeInTheDocument()
    })
    expect(resolveSourceAlias('Alpha Blog')).toBe('Alpha Blog')
  })

  it('空订阅：诚实空态 + 边界说明（设备本地/上限）', () => {
    renderSettings()
    expect(screen.getByText(/暂无订阅/)).toBeInTheDocument()
    expect(screen.getByText(new RegExp(`上限 ${SOURCE_ALIAS_LIMIT} 条`))).toBeInTheDocument()
  })

  it('加载失败：如实报错而非静默空白', () => {
    feedsState = { titles: null, isError: true }
    renderSettings()
    expect(screen.getByRole('alert')).toHaveTextContent(/订阅列表加载失败/)
  })
})
