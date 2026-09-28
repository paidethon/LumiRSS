/** R2 web6 表单修复批 — FIX-283 / FIX-290（添加来源单条 URL 表单）。
 *
 * - FIX-283：异步「校验」（feed 预览/发现）晚到的旧结果不覆盖新输入的
 *   状态——结果绑定发起时的输入版本（URL 变了就丢弃）；
 * - FIX-290：单条 URL 输入框粘贴多行内容——不再被静默截断，保留第一行
 *   并报出格式问题（多行请走批量入口；批量入口 BulkPasteDialog 逐行
 *   预览已存在，本批不重复实现）。
 *
 * 统一 stub fetch（无真实网络）；api/client 走真实模块。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DirectFeedTab } from '../components/add-source/DirectFeedTab'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function withProviders(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>
}

function renderDirectTab() {
  return render(
    withProviders(<DirectFeedTab onClose={() => {}} registerGuard={() => {}} />),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

// ===== FIX-290：多行 URL 粘贴不再静默截断 ==================================

describe('FIX-290 单条 URL 表单的多行粘贴', () => {
  it('粘贴两行 URL：保留第一行 + 诚实提示（不静默吞行）', () => {
    vi.stubGlobal('fetch', vi.fn())
    renderDirectTab()
    const input = screen.getByLabelText('RSS / Atom 地址')
    fireEvent.paste(input, {
      clipboardData: {
        getData: () => 'https://a.example/feed.xml\nhttps://b.example/rss.xml',
      },
    })
    // 输入框只保留第一行（URL 合法、可预览），不被浏览器吞成拼接串
    expect(input).toHaveValue('https://a.example/feed.xml')
    // 格式问题被报出来（role=status），并指向批量入口
    expect(screen.getByRole('status')).toHaveTextContent('2 行')
    expect(screen.getByRole('status')).toHaveTextContent('批量')
  })

  it('单行粘贴不受影响（不出现提示，不拦截默认粘贴）', () => {
    vi.stubGlobal('fetch', vi.fn())
    renderDirectTab()
    const input = screen.getByLabelText('RSS / Atom 地址')
    // jsdom 不模拟粘贴的默认赋值行为——这里断言单行不触发格式提示。
    fireEvent.paste(input, { clipboardData: { getData: () => 'https://a.example/feed.xml' } })
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('保留的第一行真的可预览：预览请求只发第一行 URL', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/api/v1/feed-preview') && init?.method === 'POST') {
        return jsonResponse({
          title: 'A Feed',
          feedUrl: 'https://a.example/feed.xml',
          siteUrl: 'https://a.example/',
          description: null,
          format: 'rss',
          alreadySubscribed: false,
        })
      }
      throw new Error(`unexpected fetch: ${init?.method ?? 'GET'} ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderDirectTab()
    const input = screen.getByLabelText('RSS / Atom 地址')
    fireEvent.paste(input, {
      clipboardData: {
        getData: () => 'https://a.example/feed.xml\nhttps://b.example/rss.xml',
      },
    })
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    expect(await screen.findByText('A Feed')).toBeInTheDocument()
    const bodies = fetchMock.mock.calls
      .filter(([u]) => String(u).includes('/api/v1/feed-preview'))
      .map(([, init]) => JSON.parse(String((init as RequestInit).body)) as { feedUrl: string })
    expect(bodies).toEqual([{ feedUrl: 'https://a.example/feed.xml' }])
  })
})

// ===== FIX-283：晚到的旧预览结果不覆盖新输入 ===============================

describe('FIX-283 异步预览结果绑定输入版本', () => {
  function deferred<T>(): { promise: Promise<T>; resolve: (v: T) => void } {
    let resolve!: (v: T) => void
    const promise = new Promise<T>((res) => {
      resolve = res
    })
    return { promise, resolve }
  }

  it('慢的旧 URL 预览晚到：不覆盖已改成新 URL 的输入状态；重按预览用新 URL', async () => {
    const slow = deferred<Response>()
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/api/v1/feed-preview') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as { feedUrl: string }
        if (body.feedUrl === 'https://a.example/feed.xml') {
          return slow.promise
        }
        return jsonResponse({
          title: 'B Feed',
          feedUrl: 'https://b.example/rss.xml',
          siteUrl: 'https://b.example/',
          description: null,
          format: 'rss',
          alreadySubscribed: false,
        })
      }
      throw new Error(`unexpected fetch: ${init?.method ?? 'GET'} ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderDirectTab()
    const input = screen.getByLabelText('RSS / Atom 地址')

    // 发起 A 的预览（慢）
    fireEvent.change(input, { target: { value: 'https://a.example/feed.xml' } })
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    expect(screen.getByRole('button', { name: /预览中/ })).toBeInTheDocument()

    // 预览未回来时把输入改成 B
    fireEvent.change(input, { target: { value: 'https://b.example/rss.xml' } })

    // A 的结果晚到 → 必须被丢弃：不出现 A 的预览面板
    slow.resolve(jsonResponse({
      title: 'A Feed',
      feedUrl: 'https://a.example/feed.xml',
      siteUrl: 'https://a.example/',
      description: null,
      format: 'rss',
      alreadySubscribed: false,
    }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '预览' })).toBeEnabled(),
    )
    expect(screen.queryByText('A Feed')).toBeNull()

    // 对 B 重新预览：正常出 B 的预览
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    expect(await screen.findByText('B Feed')).toBeInTheDocument()
  })
})
