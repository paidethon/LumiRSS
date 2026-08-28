import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, getEntries, getFeeds } from '../api/client'
import type { EntryListResponse } from '../api/types'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const entriesPage: EntryListResponse = {
  items: [
    {
      entryRef: 'e1.fake1',
      title: '第一篇',
      feedTitle: '示例源',
      author: null,
      url: null,
      publishedAt: '2026-08-28T00:00:00Z',
      read: false,
      starred: false,
    },
  ],
  nextCursor: null,
}

/** 断言 promise 以 ApiError 拒绝并返回它（供继续断言字段）。 */
async function rejectsWithApiError(promise: Promise<unknown>): Promise<ApiError> {
  const error = await promise.then(
    () => {
      throw new Error('expected the request to fail with ApiError')
    },
    (e: unknown) => e,
  )
  expect(error).toBeInstanceOf(ApiError)
  return error as ApiError
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Test A — API client base path', () => {
  it('getFeeds 请求相对路径 /api/v1/feeds（无硬编码主机）', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([]))
    vi.stubGlobal('fetch', fetchMock)

    await getFeeds()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const arg = fetchMock.mock.calls[0]![0]
    expect(arg).toBe('/api/v1/feeds')
    expect(String(arg)).not.toContain('localhost')
    expect(String(arg)).not.toContain('127.0.0.1')
  })
})

describe('Test B — entries query params（cursor opaque 透传）', () => {
  it.each(['all', 'unread', 'starred'] as const)('view=%s 转成 query', async (view) => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(entriesPage))
    vi.stubGlobal('fetch', fetchMock)

    await getEntries({ view, feedUrl: null })

    const url = new URL(String(fetchMock.mock.calls[0]![0]), 'http://local.test')
    expect(url.pathname).toBe('/api/v1/entries')
    expect(url.searchParams.get('view')).toBe(view)
    expect(url.searchParams.get('feedUrl')).toBeNull()
  })

  it('feedUrl 仅在非 null 时携带', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(entriesPage))
    vi.stubGlobal('fetch', fetchMock)

    await getEntries({ view: 'unread', feedUrl: 'https://example.com/feed.xml' })

    const url = new URL(String(fetchMock.mock.calls[0]![0]), 'http://local.test')
    expect(url.searchParams.get('feedUrl')).toBe('https://example.com/feed.xml')
  })

  it('cursor 作为 opaque string 原样传递（URL-safe fake cursor）', async () => {
    const cursor = 'c1.fake-_cursor_0005'
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(entriesPage))
    vi.stubGlobal('fetch', fetchMock)

    await getEntries({ view: 'all', feedUrl: null, cursor })

    const url = new URL(String(fetchMock.mock.calls[0]![0]), 'http://local.test')
    // URLSearchParams 的 percent encoding 属正常 HTTP transport；
    // 读取回来必须与输入完全一致（前端没有 decode / parse / 修改）。
    expect(url.searchParams.get('cursor')).toBe(cursor)
  })

  it('cursor 为 null / 未提供时不携带 cursor 参数', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(entriesPage))
    vi.stubGlobal('fetch', fetchMock)

    await getEntries({ view: 'all', feedUrl: null, cursor: null })

    const url = new URL(String(fetchMock.mock.calls[0]![0]), 'http://local.test')
    expect(url.searchParams.get('cursor')).toBeNull()
  })
})

describe('Test C — API error 安全化', () => {
  it('BFF error envelope（4xx/5xx）→ ApiError(status/type/message)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ error: { type: 'invalid_cursor', message: 'cursor 格式错误' } }, 400),
      ),
    )

    const error = await rejectsWithApiError(getFeeds())
    expect(error.status).toBe(400)
    expect(error.type).toBe('invalid_cursor')
    expect(error.message).toBe('cursor 格式错误')
  })

  it('非 JSON 响应（HTML 错误页）→ 安全 fallback message，不泄漏原文', async () => {
    const html = '<html><body><h1>502 Bad Gateway</h1><pre>STACKTRACE...</pre></body></html>'
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(html, { status: 502, headers: { 'content-type': 'text/html' } })),
    )

    const error = await rejectsWithApiError(getFeeds())
    expect(error.status).toBe(502)
    expect(error.message).not.toContain('STACKTRACE')
    expect(error.message).not.toContain('<html>')
  })

  it('422 detail 数组形状 → 安全 fallback', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ detail: [{ msg: 'bad input' }] }, 422)),
    )

    const error = await rejectsWithApiError(getEntries({ view: 'all', feedUrl: null }))
    expect(error.status).toBe(422)
    expect(error.type).toBe('http_error')
    expect(error.message).not.toContain('bad input')
  })

  it('真正的网络失败 → ApiError(status=0)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    const error = await rejectsWithApiError(getFeeds())
    expect(error.status).toBe(0)
    expect(error.type).toBe('network_error')
  })

  it('预先 abort 的 signal → 原样 rethrow AbortError，不包装成 ApiError', async () => {
    const controller = new AbortController()
    controller.abort()
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    const error = await getFeeds(controller.signal).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(DOMException)
    expect((error as DOMException).name).toBe('AbortError')
    expect(error).not.toBeInstanceOf(ApiError)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('fetch 抛 AbortError → 原样 rethrow，不包装成 ApiError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new DOMException('The request was aborted.', 'AbortError')),
    )

    const error = await getFeeds().catch((e: unknown) => e)
    expect(error).toBeInstanceOf(DOMException)
    expect((error as DOMException).name).toBe('AbortError')
    expect(error).not.toBeInstanceOf(ApiError)
  })
})
