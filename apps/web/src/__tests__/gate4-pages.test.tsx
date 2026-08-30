/** Gate 4 测试 — Subscriptions & Search Surfaces（0011 Spec AC11）。
 *
 * - SubscriptionsPage：真实只读 feeds + 本地过滤 + CRUD 禁用 0013 徽标
 *   + 未分组折叠 + 点 feed 回首页；
 * - SearchPage：提交/取消/历史（上限/去重/单条删/清空）+ 诚实空态
 *   （不冒充全局搜索）；
 * - search-history 纯函数单测。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useReaderUi } from '../store/reader-ui'
import SubscriptionsPage from '../components/pages/SubscriptionsPage'
import SearchPage from '../components/pages/SearchPage'
import {
  clearSearchHistory,
  pushSearchHistory,
  readSearchHistory,
  removeFromSearchHistory,
} from '../lib/search-history'

const FEEDS = [
  { title: '阮一峰的网络日志', feedUrl: 'https://www.ruanyifeng.com/blog/atom.xml', category: null },
  { title: 'IT之家', feedUrl: 'https://ithome.com/rss', category: null },
  { title: 'OpenAI Blog', feedUrl: 'https://openai.com/blog/rss.xml', category: null },
]

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function withProviders(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

beforeEach(() => {
  localStorage.clear()
  useReaderUi.setState({ section: 'subscriptions', view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('SubscriptionsPage（AC11）', () => {
  function renderPage() {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        if (String(input).startsWith('/api/v1/feeds')) return jsonResponse(FEEDS)
        throw new Error(`unexpected fetch: ${input}`)
      }),
    )
    return render(withProviders(<SubscriptionsPage />))
  }

  it('真实只读 feed 列表：标题 + feedUrl（统一 RSS 图标，无 favicon 抓取）', async () => {
    renderPage()
    expect(await screen.findByText('阮一峰的网络日志')).toBeInTheDocument()
    expect(screen.getByText('https://ithome.com/rss')).toBeInTheDocument()
    expect(screen.getByText('https://openai.com/blog/rss.xml')).toBeInTheDocument()
  })

  it('未分组折叠：aria-expanded/controls + 数量；点击折叠隐藏列表', async () => {
    renderPage()
    await screen.findByText('阮一峰的网络日志')
    const toggle = screen.getByRole('button', { name: /未分组/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(toggle).toHaveAttribute('aria-controls', 'subscriptions-ungrouped')
    expect(toggle.textContent).toContain('3')
    fireEvent.click(toggle)
    expect(screen.queryByText('阮一峰的网络日志')).toBeNull()
  })

  it('本地过滤：输入关键词 → 只剩匹配项；计数 x/y 诚实显示', async () => {
    renderPage()
    await screen.findByText('阮一峰的网络日志')
    const input = screen.getByRole('searchbox', { name: '搜索订阅源' })
    fireEvent.change(input, { target: { value: 'IT之家' } })
    expect(screen.getByText('IT之家')).toBeInTheDocument()
    expect(screen.queryByText('阮一峰的网络日志')).toBeNull()
    // 计数：过滤后 / 总数
    expect(screen.getByText('1 / 3')).toBeInTheDocument()
  })

  it('CRUD 动作禁用 + 0013 徽标（添加 RSS / OPML / 分组管理）', async () => {
    renderPage()
    await screen.findByText('阮一峰的网络日志')
    for (const label of ['添加 RSS', 'OPML 导入', '分组管理']) {
      const el = screen.getByText(label).closest('[aria-disabled="true"]')
      expect(el).not.toBeNull()
    }
    const badges = screen.getAllByText('0013')
    expect(badges.length).toBe(3)
    // 无可点击的假按钮
    expect(screen.queryByRole('button', { name: /添加 RSS/ })).toBeNull()
  })

  it('点 feed → section 回首页 + selectedFeedUrl 更新（AC4 语义）', async () => {
    renderPage()
    fireEvent.click(await screen.findByText('阮一峰的网络日志'))
    const s = useReaderUi.getState()
    expect(s.section).toBe('home')
    expect(s.scope).toEqual({ kind: 'rss-feed', feedUrl: 'https://www.ruanyifeng.com/blog/atom.xml' })
  })

  it('加载失败：错误状态 + 重试', async () => {
    let fail = true
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() =>
        fail
          ? jsonResponse({ error: { type: 'upstream_error', message: '上游不可用' } }, 502)
          : jsonResponse(FEEDS),
      ),
    )
    render(withProviders(<SubscriptionsPage />))
    expect(await screen.findByText('订阅加载失败')).toBeInTheDocument()
    fail = false
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByText('阮一峰的网络日志')).toBeInTheDocument()
  })

  it('无订阅：空态（FreshRSS 语义，不编造示例源）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() => jsonResponse([])),
    )
    render(withProviders(<SubscriptionsPage />))
    expect(await screen.findByText('还没有订阅源')).toBeInTheDocument()
  })
})

describe('SearchPage（AC11 / 决策 2）', () => {
  it('诚实空态：全局搜索能力尚未接入（0011a 候选说明）', () => {
    render(withProviders(<SearchPage />))
    expect(screen.getByText('全局搜索能力尚未接入')).toBeInTheDocument()
    expect(screen.getByText(/0011a/)).toBeInTheDocument()
    // 不渲染范围 chips / 热门搜索（无契约）
    expect(screen.queryByText('标题')).toBeNull()
    expect(screen.queryByText('热门搜索')).toBeNull()
  })

  it('Enter 提交 → 记录到历史 + 状态卡片（不冒充全局搜索）', () => {
    render(withProviders(<SearchPage />))
    const input = screen.getByRole('searchbox', { name: '搜索' })
    fireEvent.change(input, { target: { value: 'Midjourney V7' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(screen.getByText(/已记录「Midjourney V7」/)).toBeInTheDocument()
    // 历史出现该词条
    expect(screen.getByRole('button', { name: 'Midjourney V7' })).toBeInTheDocument()
  })

  it('取消按钮：清空输入与提交态', () => {
    render(withProviders(<SearchPage />))
    const input = screen.getByRole('searchbox', { name: '搜索' })
    fireEvent.change(input, { target: { value: 'test' } })
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(input).toHaveValue('')
    expect(screen.queryByText(/已记录/)).toBeNull()
  })

  it('历史：单条删除 + 清空', () => {
    localStorage.setItem('lumirss-search-history', JSON.stringify(['a', 'b']))
    render(withProviders(<SearchPage />))
    fireEvent.click(screen.getByRole('button', { name: '删除历史「a」' }))
    expect(screen.queryByRole('button', { name: 'a' })).toBeNull()
    expect(screen.getByRole('button', { name: 'b' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '清空' }))
    expect(screen.queryByRole('button', { name: 'b' })).toBeNull()
  })

  it('点历史词条 → 填入输入框并显示状态卡片', () => {
    localStorage.setItem('lumirss-search-history', JSON.stringify(['RAG']))
    render(withProviders(<SearchPage />))
    fireEvent.click(screen.getByRole('button', { name: 'RAG' }))
    expect(screen.getByRole('searchbox', { name: '搜索' })).toHaveValue('RAG')
    expect(screen.getByText(/已记录「RAG」/)).toBeInTheDocument()
  })
})

describe('search-history 纯函数', () => {
  it('push：置顶去重 + 上限 10', () => {
    const nine = ['1', '2', '3', '4', '5', '6', '7', '8', '9']
    expect(pushSearchHistory(nine, '10')).toEqual(['10', '1', '2', '3', '4', '5', '6', '7', '8', '9'])
    // 去重：已有词条置顶移位
    const withTwo = ['1', '2', '3']
    expect(pushSearchHistory(withTwo, '2')).toEqual(['2', '1', '3'])
    // 超限截断
    const ten = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10']
    expect(pushSearchHistory(ten, '11')).toEqual(['11', '1', '2', '3', '4', '5', '6', '7', '8', '9'])
    // 空白不入
    expect(pushSearchHistory(['a'], '   ')).toEqual(['a'])
  })

  it('remove / clear', () => {
    expect(removeFromSearchHistory(['a', 'b'], 'a')).toEqual(['b'])
    expect(clearSearchHistory(['a', 'b'])).toEqual([])
  })

  it('read：损坏 JSON / 非数组安全降级', () => {
    localStorage.setItem('lumirss-search-history', '{bad json')
    expect(readSearchHistory()).toEqual([])
    localStorage.setItem('lumirss-search-history', '"not-array"')
    expect(readSearchHistory()).toEqual([])
  })

  it('push 持久化到 localStorage（可跨会话读取）', () => {
    pushSearchHistory([], '持久化词条')
    expect(readSearchHistory()).toEqual(['持久化词条'])
  })
})
