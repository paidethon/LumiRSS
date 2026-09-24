/** N122/N123 UI — 剪藏锁定 + 刷新候选 + 清理预览。
 *
 * - N122：锁定 toggle（PUT lock）→ 刷新（锁定 → 候选提示 + 候选徽标；
 *   未锁定 → applied 提示）；查看候选（净化渲染）；解锁前应用被禁用；
 *   丢弃候选调用 DELETE；
 * - N123：保存流程的 清理预览 步骤（每块 keep/reason 渲染 + 确认后
 *   保存只带保留块 id；预览本身零写入）。
 * 统一 stub 全局 fetch（与 f089/f104 同一约定，真实 client 解析路径）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ClipsPage from '../components/pages/ClipsPage'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const CLIP_REF = 'library:11111111-1111-4111-8111-111111111111'

let fullPayload: Record<string, unknown>

function fullFixture(over: Record<string, unknown> = {}) {
  return {
    ref: CLIP_REF,
    url: 'https://example.com/a',
    title: '测试剪辑',
    byline: null,
    fetchedAt: '2026-09-20T00:00:00Z',
    createdAt: '2026-09-20T00:00:00Z',
    locked: false,
    content: { html: '<p>当前正文</p>', text: '当前正文' },
    original: { html: '<p>当前正文</p>', text: '当前正文' },
    revised: null,
    candidate: null,
    ...over,
  }
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <ClipsPage />
    </QueryClientProvider>,
  )
}

async function openReadDialog() {
  renderPage()
  const titleButton = await screen.findByRole('button', { name: '测试剪辑' })
  fireEvent.click(titleButton)
  await screen.findByText('当前正文')
}

function stubFetch(handler: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response> | Response) {
  const fetchMock = vi.fn().mockImplementation(handler)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

beforeEach(() => {
  fullPayload = fullFixture()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

const LIST_BODY = {
  items: [
    {
      ref: CLIP_REF,
      url: 'https://example.com/a',
      title: '测试剪辑',
      byline: null,
      createdAt: '2026-09-20T00:00:00Z',
      fetchedAt: '2026-09-20T00:00:00Z',
    },
  ],
  nextCursor: null,
}

function baseHandler(input: RequestInfo | URL, init?: RequestInit) {
  const url = String(input)
  const method = init?.method ?? 'GET'
  if (method === 'GET' && /\/library\/clips\?.*$/.test(url)) {
    return jsonResponse(LIST_BODY)
  }
  if (method === 'GET' && url.endsWith('/full')) {
    return jsonResponse(fullPayload)
  }
  return jsonResponse({})
}

describe('N122 剪藏版本锁定', () => {
  it('锁定 toggle 调用 PUT lock 并翻转文案（已锁定）', async () => {
    const fetchMock = stubFetch((input, init) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'PUT' && url.endsWith('/lock')) {
        fullPayload = { ...fullPayload, locked: true }
        return jsonResponse({ ref: CLIP_REF, locked: true })
      }
      return baseHandler(input, init)
    })
    await openReadDialog()

    fireEvent.click(screen.getByRole('button', { name: '锁定' }))
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        (c) => String(c[0]).endsWith('/lock') && c[1]?.method === 'PUT',
      )
      expect(call).toBeDefined()
      expect(JSON.parse(String(call?.[1]?.body ?? '{}'))).toEqual({ locked: true })
    })
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '已锁定' })).toBeInTheDocument()
    })
  })

  it('锁定时刷新 → 候选提示 + 候选徽标 + 查看候选（净化渲染）；解锁前应用禁用', async () => {
    let refreshed = false
    const fetchMock = stubFetch((input, init) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'POST' && url.endsWith('/refresh')) {
        refreshed = true
        return jsonResponse({ ref: CLIP_REF, status: 'candidate', locked: true, title: '新版本' })
      }
      if (method === 'GET' && url.endsWith('/full') && refreshed) {
        return jsonResponse(
          fullFixture({
            locked: true,
            candidate: { title: '新版本', fetchedAt: '2026-09-21T00:00:00Z', text: '候选正文' },
          }),
        )
      }
      if (method === 'GET' && url.endsWith('/candidate')) {
        return jsonResponse({
          ref: CLIP_REF,
          title: '新版本',
          fetchedAt: '2026-09-21T00:00:00Z',
          contentHtml: '<p>候选正文<script>alert(1)</script></p>',
          contentText: '候选正文',
        })
      }
      if (method === 'DELETE' && url.endsWith('/candidate')) {
        return new Response(null, { status: 204 })
      }
      return baseHandler(input, init)
    })
    await openReadDialog()

    fireEvent.click(screen.getByRole('button', { name: '刷新' }))
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        (c) => String(c[0]).endsWith('/refresh') && c[1]?.method === 'POST',
      )
      expect(call).toBeDefined()
    })
    expect(await screen.findByText(/只存为候选版本/)).toBeInTheDocument()
    expect(await screen.findByText('有候选版本')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '查看候选版本' }))
    expect(await screen.findByText('候选正文')).toBeInTheDocument()
    // 候选正文经 DOMPurify：script 永不渲染
    expect(screen.queryByText('alert(1)')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /解锁后才能应用/ })).toBeDisabled()
    expect(screen.getByText('剪藏已锁定：应用候选前需要先解锁。')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '丢弃候选' }))
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        (c) => String(c[0]).endsWith('/candidate') && c[1]?.method === 'DELETE',
      )
      expect(call).toBeDefined()
    })
  })

  it('未锁定时刷新 → applied 提示（原始版本保留语义）', async () => {
    stubFetch((input, init) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'POST' && url.endsWith('/refresh')) {
        return jsonResponse({ ref: CLIP_REF, status: 'applied', locked: false, revised: true })
      }
      return baseHandler(input, init)
    })
    await openReadDialog()
    fireEvent.click(screen.getByRole('button', { name: '刷新' }))
    expect(await screen.findByText(/已应用重新抓取的内容/)).toBeInTheDocument()
  })
})

describe('N123 清理预览', () => {
  it('fetch 后 清理预览 → 逐块建议 + 确认后保存只带保留块', async () => {
    const fetchMock = stubFetch((input, init) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'GET' && /\/library\/clips\?.*$/.test(url)) {
        return jsonResponse({ items: [], nextCursor: null })
      }
      if (method === 'POST' && url.endsWith('/library/clips/fetch')) {
        return jsonResponse({
          url: 'https://example.com/new',
          finalUrl: 'https://example.com/new',
          title: '待剪文章',
          byline: null,
          contentHtml:
            '<p>导语段落。</p><p><a href="/1">首页</a> <a href="/2">目录</a> <a href="/3">下一篇</a></p><p>结论。</p>',
          contentText: '导语段落。首页 目录 下一篇 结论。',
        })
      }
      if (method === 'POST' && url.endsWith('/preview-cleanup')) {
        return jsonResponse({
          blocks: [
            { id: 'b0', text: '导语段落。', keep: true, reason: 'paragraph' },
            { id: 'b1', text: '首页 目录 下一篇', keep: false, reason: 'link_list' },
            { id: 'b2', text: '结论。', keep: true, reason: 'paragraph' },
          ],
          keepCount: 2,
          totalCount: 3,
        })
      }
      if (method === 'POST' && url.endsWith('/library/clips')) {
        return jsonResponse({
          ref: CLIP_REF,
          url: 'https://example.com/new',
          title: '待剪文章',
          byline: null,
          createdAt: '2026-09-22T00:00:00Z',
          fetchedAt: '2026-09-22T00:00:00Z',
          contentHtml: '<p>导语段落。</p><p>结论。</p>',
          contentText: '导语段落。结论。',
        })
      }
      if (method === 'PATCH' && url.endsWith('/revision')) {
        return jsonResponse({ revised: true })
      }
      return jsonResponse({})
    })
    renderPage()

    fireEvent.change(screen.getByLabelText('粘贴链接'), {
      target: { value: 'https://example.com/new' },
    })
    fireEvent.click(screen.getByRole('button', { name: '剪藏' }))
    await screen.findByRole('region', { name: '确认剪藏内容' })

    fireEvent.click(screen.getByRole('button', { name: '清理预览' }))
    // 预览建议渲染（link_list 建议移除；段落保留）
    expect(await screen.findByText(/建议移除 1 块/)).toBeInTheDocument()
    expect(screen.getByText('链接列表')).toBeInTheDocument()
    expect(
      screen
        .getAllByText('导语段落。')
        .length,
    ).toBeGreaterThan(0)
    // 预览零写入断言：进入确认 → 未调用任何保存
    expect(
      fetchMock.mock.calls.some((c) => String(c[0]).endsWith('/library/clips') && (c[1]?.method ?? 'GET') === 'POST'),
    ).toBe(false)
    expect(
      fetchMock.mock.calls.some((c) => String(c[0]).endsWith('/revision')),
    ).toBe(false)

    fireEvent.click(screen.getByRole('button', { name: '保存并应用清理' }))
    await waitFor(() => {
      expect(mocksCreateCalled(fetchMock)).toBe(true)
    })
    await waitFor(() => {
      const calls = fetchMock.mock.calls.filter(
        (c) => String(c[0]).endsWith('/revision') && c[1]?.method === 'PATCH',
      )
      expect(calls.length).toBeGreaterThan(0)
      const body = JSON.parse(String(calls[0]?.[1]?.body ?? '{}'))
      expect(body.blocks).toEqual(['b0', 'b2'])
      expect(body.note).toBe('清理预览确认')
    })
    expect(await screen.findByText(/已应用清理/)).toBeInTheDocument()
  })
})

function mocksCreateCalled(fetchMock: ReturnType<typeof vi.fn>): boolean {
  return fetchMock.mock.calls.some(
    (c: unknown[]) =>
      String(c[0]).endsWith('/library/clips') &&
      (c[1] as RequestInit | undefined)?.method === 'POST',
  )
}
