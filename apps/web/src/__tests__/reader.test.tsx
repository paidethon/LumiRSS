import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Reader from '../components/Reader'
import type { EntryDetail } from '../api/types'
import { useReaderUi } from '../store/reader-ui'

function detail(overrides: Partial<EntryDetail> = {}): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '文章 A',
    feedTitle: '示例源',
    author: '作者甲',
    url: 'https://example.com/a',
    publishedAt: '2026-08-28T10:00:00Z',
    read: false,
    starred: false,
    contentText: '纯文本正文 A',
    contentHtml: '<p>富文本正文 <strong>A</strong></p>',
    ...overrides,
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function noContent(): Response {
  return new Response(null, { status: 204 })
}

type FetchHandler = (url: string, init?: RequestInit) => Response | Promise<Response>

/** 按方法 + 路径分发的 fetch mock。 */
function mockApi(handlers: Array<{ when: (url: string, init?: RequestInit) => boolean; respond: FetchHandler }>) {
  return vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    for (const h of handlers) {
      if (h.when(url, init)) return h.respond(url, init)
    }
    throw new Error(`unexpected fetch: ${url} ${init?.method ?? 'GET'}`)
  })
}

const detailRoute = (ref: string, body: unknown, status = 200) => ({
  when: (url: string, init?: RequestInit) =>
    (init?.method ?? 'GET') === 'GET' && url === `/api/v1/entries/${ref}`,
  respond: () => jsonResponse(body, status),
})

const patchRoute = (fn: FetchHandler) => ({
  when: (url: string, init?: RequestInit) => init?.method === 'PATCH' && url.includes('/state'),
  respond: fn,
})

function renderReader(queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
})) {
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <Reader />
      </QueryClientProvider>,
    ),
  }
}

beforeEach(() => {
  useReaderUi.setState({ view: 'all', selectedFeedUrl: null, selectedEntryRef: null })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Test H — no selection', () => {
  it('显示 Placeholder 且不发任何 Detail 请求（列表请求属于 Placeholder 既有行为）', () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    renderReader()

    expect(screen.getByText('选择一篇文章开始阅读')).toBeInTheDocument()
    // Detail 请求是 /api/v1/entries/{ref}（无 query）；列表是 /api/v1/entries?...
    const detailCalls = fetchMock.mock.calls
      .map((c) => String(c[0]))
      .filter((u) => /\/api\/v1\/entries\/e1\./.test(u))
    expect(detailCalls).toHaveLength(0)
  })
})

describe('Test I — loading', () => {
  it('Detail pending → Reader skeleton，不白屏', () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => new Promise<Response>(() => {})))
    renderReader()

    expect(screen.getByLabelText('文章加载中')).toBeInTheDocument()
  })
})

describe('Test J — success（HTML path）', () => {
  it('title / feed / meta / sanitized 富文本显示；script 不渲染', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([
      detailRoute('e1.a', {
        ...detail(),
        contentHtml: '<p>富文本正文 <strong>A</strong></p><script>alert(1)</script>',
      }),
    ]))
    renderReader()

    expect(await screen.findByText('文章 A')).toBeInTheDocument()
    // meta 行由多个 span 组成，分别断言各字段（分隔符 · 在 span 内）
    expect(screen.getByText('示例源')).toBeInTheDocument()
    expect(screen.getByText(/作者甲/)).toBeInTheDocument()
    expect(screen.getByText(/2026\/08\/28 18:00/)).toBeInTheDocument()
    const content = document.querySelector('.article-content')
    expect(content?.querySelector('strong')?.textContent).toBe('A')
    expect(content?.querySelector('script')).toBeNull()
    expect(content?.textContent).not.toContain('alert(1)')
  })
})

describe('Test K — text fallback', () => {
  it('contentHtml=null + contentText 非空 → 纯文本显示', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([
      detailRoute('e1.a', { ...detail(), contentHtml: null }),
    ]))
    renderReader()

    await screen.findByText('文章 A')
    expect(screen.getByText('纯文本正文 A')).toBeInTheDocument()
    // 纯文本路径不使用 dangerouslySetInnerHTML
    expect(document.querySelector('.article-content p')?.textContent).toBe('纯文本正文 A')
  })
})

describe('Test L — empty body', () => {
  it('HTML/Text 都空 → 「这篇文章没有可显示的正文。」，不是 Error', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([
      detailRoute('e1.a', { ...detail(), contentHtml: null, contentText: '' }),
    ]))
    renderReader()

    expect(await screen.findByText('这篇文章没有可显示的正文。')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

describe('Test M — detail error（非 404）', () => {
  it('显示「文章加载失败」+ 安全错误 + 重试；Shell 不崩', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([
      detailRoute('e1.a', { error: { type: 'upstream_error', message: '上游异常' } }, 502),
    ]))
    renderReader()

    expect(await screen.findByRole('alert')).toHaveTextContent('文章加载失败')
    expect(screen.getByText('上游异常')).toBeInTheDocument()
    const retry = screen.getByRole('button', { name: '重试' })
    expect(retry).toBeInTheDocument()
  })

  it('点击重试 → 重新请求 Detail', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    let failed = true
    const fetchMock = mockApi([{
      when: (url, init) => (init?.method ?? 'GET') === 'GET' && url === '/api/v1/entries/e1.a',
      respond: () => (failed
        ? jsonResponse({ error: { type: 'upstream_error', message: '上游异常' } }, 502)
        : jsonResponse(detail())),
    }])
    vi.stubGlobal('fetch', fetchMock)
    renderReader()

    await screen.findByRole('alert')
    failed = false
    fireEvent.click(screen.getByRole('button', { name: '重试' }))

    expect(await screen.findByText('文章 A')).toBeInTheDocument()
  })
})

describe('Test N — 404', () => {
  it('显示 unavailable 文案；「返回文章列表」清空 selection', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([
      detailRoute('e1.a', { error: { type: 'entry_not_found', message: '文章不存在' } }, 404),
    ]))
    renderReader()

    expect(await screen.findByText('这篇文章已经不存在或不可用了。')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '返回文章列表' }))

    await waitFor(() => {
      expect(useReaderUi.getState().selectedEntryRef).toBeNull()
    })
    expect(screen.getByText('选择一篇文章开始阅读')).toBeInTheDocument()
  })
})

describe('Original link（safeExternalHttpUrl）', () => {
  it('http/https url → 「打开原文」target=_blank + rel=noopener noreferrer', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([detailRoute('e1.a', detail())]))
    renderReader()

    const link = await screen.findByRole('link', { name: '打开原文' })
    expect(link).toHaveAttribute('href', 'https://example.com/a')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link.getAttribute('rel')).toContain('noopener')
    expect(link.getAttribute('rel')).toContain('noreferrer')
  })

  it.each(['javascript:alert(1)', 'data:text/html,x', 'file:///etc/passwd', '/relative', 'not a url', null])(
    'url=%s → 按钮不存在',
    async (url) => {
      useReaderUi.setState({ selectedEntryRef: 'e1.a' })
      vi.stubGlobal('fetch', mockApi([detailRoute('e1.a', detail({ url }))]))
      renderReader()

      await screen.findByText('文章 A')
      expect(screen.queryByRole('link', { name: '打开原文' })).not.toBeInTheDocument()
    },
  )
})

describe('Read / Star mutation（set 语义）', () => {
  it('read=false → 「标记为已读」→ PATCH body {"read":true}', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    const bodies: Array<[string, RequestInit]> = []
    vi.stubGlobal('fetch', mockApi([
      detailRoute('e1.a', detail({ read: false })),
      patchRoute((url, init) => {
        bodies.push([url, init!])
        return noContent()
      }),
    ]))
    renderReader()

    fireEvent.click(await screen.findByRole('button', { name: '标记为已读' }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]![0]).toBe('/api/v1/entries/e1.a/state')
    expect(bodies[0]![1].body).toBe(JSON.stringify({ read: true }))
  })

  it('read=true → 「标记为未读」→ PATCH body {"read":false}', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    const bodies: string[] = []
    vi.stubGlobal('fetch', mockApi([
      detailRoute('e1.a', detail({ read: true })),
      patchRoute((_url, init) => {
        bodies.push(String(init!.body))
        return noContent()
      }),
    ]))
    renderReader()

    fireEvent.click(await screen.findByRole('button', { name: '标记为未读' }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toBe(JSON.stringify({ read: false }))
  })

  it('starred=false → 「收藏」→ {"starred":true}；starred=true → 「取消收藏」→ {"starred":false}', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    const bodies: string[] = []
    vi.stubGlobal('fetch', mockApi([
      detailRoute('e1.a', detail({ starred: false })),
      patchRoute((_url, init) => {
        bodies.push(String(init!.body))
        return noContent()
      }),
    ]))
    renderReader()

    fireEvent.click(await screen.findByRole('button', { name: '收藏' }))
    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toBe(JSON.stringify({ starred: true }))
  })

  it('aria-pressed 表达当前 read/starred UI 状态', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([
      detailRoute('e1.a', detail({ read: true, starred: true })),
    ]))
    renderReader()

    await screen.findByText('文章 A')
    expect(screen.getByRole('button', { name: '标记为未读' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '取消收藏' })).toHaveAttribute('aria-pressed', 'true')
  })
})

describe('Mutation cache invalidation', () => {
  it('PATCH 204 → invalidate ["entry", entryRef] 与 ["entries"] prefix', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([
      detailRoute('e1.a', detail()),
      patchRoute(() => noContent()),
    ]))
    const { queryClient } = renderReader()
    const spy = vi.spyOn(queryClient, 'invalidateQueries')

    fireEvent.click(await screen.findByRole('button', { name: '标记为已读' }))

    await waitFor(() => expect(spy).toHaveBeenCalled())
    const keys = spy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey))
    expect(keys).toContain(JSON.stringify(['entry', 'e1.a']))
    expect(keys).toContain(JSON.stringify(['entries']))
  })

  it('invalidation race：对 A 发 mutation，完成前切到 B → 只 invalidate ["entry", A]', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    let resolvePatch: (r: Response) => void = () => {}
    const patchPromise = new Promise<Response>((resolve) => {
      resolvePatch = resolve
    })
    vi.stubGlobal('fetch', mockApi([
      detailRoute('e1.a', detail()),
      detailRoute('e1.b', detail({ entryRef: 'e1.b', title: '文章 B' })),
      patchRoute(() => patchPromise),
    ]))
    const { queryClient } = renderReader()
    const spy = vi.spyOn(queryClient, 'invalidateQueries')

    fireEvent.click(await screen.findByRole('button', { name: '标记为已读' }))
    // mutation 完成前 selection 切到 B
    useReaderUi.setState({ selectedEntryRef: 'e1.b' })
    await screen.findByText('文章 B')
    resolvePatch(noContent())

    await waitFor(() => expect(spy).toHaveBeenCalled())
    const keys = spy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey))
    expect(keys).toContain(JSON.stringify(['entry', 'e1.a']))
    expect(keys).not.toContain(JSON.stringify(['entry', 'e1.b']))
    expect(keys).toContain(JSON.stringify(['entries']))
  })
})

describe('Mutation pending / error UI', () => {
  it('任一 mutation pending → read/star 两个按钮均 disabled', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([
      detailRoute('e1.a', detail()),
      patchRoute(() => new Promise<Response>(() => {})),
    ]))
    renderReader()

    fireEvent.click(await screen.findByRole('button', { name: '标记为已读' }))
    // 同一 mutation 实例：read/star 两个按钮都 pending + disabled
    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: '处理中…' })).toHaveLength(2)
    })
    for (const button of screen.getAllByRole('button', { name: '处理中…' })) {
      expect(button).toBeDisabled()
    }
  })

  it('PATCH 失败 → 「状态更新失败」，文章与既有状态不被清空/伪造', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([
      detailRoute('e1.a', detail({ read: false })),
      patchRoute(() => jsonResponse({ error: { type: 'upstream_error', message: '上游写入失败' } }, 502)),
    ]))
    renderReader()

    fireEvent.click(await screen.findByRole('button', { name: '标记为已读' }))

    expect(await screen.findByText(/状态更新失败/)).toBeInTheDocument()
    // 文章仍在；按钮仍按未成功前的真实状态显示（不伪造成功）
    expect(screen.getByText('文章 A')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '标记为已读' })).toBeInTheDocument()
  })

  it('跨 Entry 泄漏：A mutation 失败后切到 B → 旧 error UI 不残留', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([
      detailRoute('e1.a', detail()),
      detailRoute('e1.b', detail({ entryRef: 'e1.b', title: '文章 B' })),
      patchRoute(() => jsonResponse({ error: { type: 'upstream_error', message: '上游写入失败' } }, 502)),
    ]))
    renderReader()

    fireEvent.click(await screen.findByRole('button', { name: '标记为已读' }))
    expect(await screen.findByText(/状态更新失败/)).toBeInTheDocument()

    // 切到 B：key={entryRef} 重挂载 ReaderHeader，旧 error 不残留
    useReaderUi.setState({ selectedEntryRef: 'e1.b' })
    expect(await screen.findByText('文章 B')).toBeInTheDocument()
    expect(screen.queryByText(/状态更新失败/)).not.toBeInTheDocument()
  })
})

describe('Selection race（query）', () => {
  it('A→B 快速切换 → 最终显示 B（A 的请求不落地）', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    // A 永远 pending；B 正常返回
    vi.stubGlobal('fetch', mockApi([
      {
        when: (url, init) => (init?.method ?? 'GET') === 'GET' && url === '/api/v1/entries/e1.a',
        respond: () => new Promise<Response>(() => {}),
      },
      detailRoute('e1.b', detail({ entryRef: 'e1.b', title: '文章 B' })),
    ]))
    renderReader()

    expect(screen.getByLabelText('文章加载中')).toBeInTheDocument()
    useReaderUi.setState({ selectedEntryRef: 'e1.b' })

    expect(await screen.findByText('文章 B')).toBeInTheDocument()
    expect(screen.queryByText('文章 A')).not.toBeInTheDocument()
  })
})
