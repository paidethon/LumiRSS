/** Gate 4 测试 — Subscriptions & Search Surfaces（0011 Spec AC11；
 * 0013 Gate 3 后订阅页改为管理视角 /api/v1/subscriptions 契约）。
 *
 * - SubscriptionsPage：真实分类分组 + 本地过滤 + OPML 真实入口
 *   （0013 Gate 4）+ 点 feed 回首页；
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

const SUBSCRIPTIONS = [
  {
    subscriptionRef: 's1.ZmVlZC8x',
    title: '阮一峰的网络日志',
    feedUrl: 'https://www.ruanyifeng.com/blog/atom.xml',
    category: { id: 'user/-/label/技术', label: '技术' },
  },
  {
    subscriptionRef: 's1.ZmVlZC8y',
    title: 'IT之家',
    feedUrl: 'https://ithome.com/rss',
    category: { id: 'user/-/label/技术', label: '技术' },
  },
  {
    subscriptionRef: 's1.ZmVlZC8z',
    title: 'OpenAI Blog',
    feedUrl: 'https://openai.com/blog/rss.xml',
    category: null,
  },
]

const CATEGORIES = [
  { id: 'user/-/label/技术', label: '技术' },
  { id: 'user/-/label/未分类', label: '未分类' },
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
        const url = String(input)
        if (url === '/api/v1/subscriptions') return jsonResponse(SUBSCRIPTIONS)
        if (url === '/api/v1/categories') return jsonResponse(CATEGORIES)
        throw new Error(`unexpected fetch: ${url}`)
      }),
    )
    return render(withProviders(<SubscriptionsPage />))
  }

  it('真实订阅列表：标题 + 域名（统一 RSS 图标，无 favicon 抓取）', async () => {
    renderPage()
    expect(await screen.findByText('阮一峰的网络日志')).toBeInTheDocument()
    expect(screen.getByText('ithome.com')).toBeInTheDocument()
    expect(screen.getByText('openai.com')).toBeInTheDocument()
  })

  it('真实分类分组：技术（2）+ 未分组（1）；点击折叠隐藏列表', async () => {
    renderPage()
    await screen.findByText('阮一峰的网络日志')
    const techToggle = screen.getByRole('button', { name: /^技术/ })
    expect(techToggle).toHaveAttribute('aria-expanded', 'true')
    expect(techToggle.textContent).toContain('2')
    const ungrouped = screen.getByRole('button', { name: /未分组/ })
    expect(ungrouped.textContent).toContain('1')
    fireEvent.click(techToggle)
    expect(screen.queryByText('阮一峰的网络日志')).toBeNull()
    // 未分组不受影响
    expect(screen.getByText('OpenAI Blog')).toBeInTheDocument()
  })

  it('本地过滤：输入关键词 → 只剩匹配项；分组计数同步', async () => {
    renderPage()
    await screen.findByText('阮一峰的网络日志')
    const input = screen.getByRole('searchbox', { name: '搜索订阅源' })
    fireEvent.change(input, { target: { value: 'IT之家' } })
    expect(screen.getByText('IT之家')).toBeInTheDocument()
    expect(screen.queryByText('阮一峰的网络日志')).toBeNull()
    expect(screen.queryByText('OpenAI Blog')).toBeNull()
    // 技术组只剩 1 个匹配
    expect(screen.getByRole('button', { name: /^技术/ }).textContent).toContain('1')
  })

  it('OPML 导入真实入口（0013 Gate 4）；添加来源 已是真实入口（Gate 2）', async () => {
    renderPage()
    await screen.findByText('阮一峰的网络日志')
    // 添加来源 + 导入 OPML：均为真实可点击按钮（不再有 disabled 版本）
    expect(screen.queryByRole('button', { name: /添加来源/ })).not.toBeDisabled()
    expect(screen.queryByRole('button', { name: /导入 OPML/ })).not.toBeDisabled()
  })

  it('添加来源：打开三模式对话框（0014）', async () => {
    renderPage()
    await screen.findByText('阮一峰的网络日志')
    fireEvent.click(screen.getByRole('button', { name: /添加来源/ }))
    expect(await screen.findByRole('dialog', { name: '添加来源' })).toBeInTheDocument()
    // 三种来源模式均可见；默认落在直接 RSS/Atom
    expect(screen.getByRole('tab', { name: 'RSS / Atom' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: '网站' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'RSSHub' })).toBeInTheDocument()
    expect(screen.getByLabelText('RSS / Atom 地址')).toBeInTheDocument()
  })

  it('点 feed → section 回首页 + scope 更新（AC4 语义）', async () => {
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
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = String(input)
        if (url === '/api/v1/categories') return jsonResponse(CATEGORIES)
        if (url === '/api/v1/subscriptions') {
          return fail
            ? jsonResponse({ error: { type: 'upstream_error', message: '上游不可用' } }, 502)
            : jsonResponse(SUBSCRIPTIONS)
        }
        throw new Error(`unexpected fetch: ${url}`)
      }),
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
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = String(input)
        if (url === '/api/v1/subscriptions') return jsonResponse([])
        if (url === '/api/v1/categories') return jsonResponse(CATEGORIES)
        throw new Error(`unexpected fetch: ${url}`)
      }),
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
