/** F095 UI — 会话搜索：下拉结果 + 高亮（转义）、截断标注、点击打开。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ThreadSearchBox, highlightSnippet } from '../components/AgentW5'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const HITS = {
  items: [
    {
      threadId: 'th-1',
      threadTitle: '资料调研',
      messageIndex: 4,
      role: 'user',
      snippet: '帮我找 <b>阅读器</b> 相关的书签',
    },
  ],
  truncated: true,
}

function renderBox(onOpen = () => {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <ThreadSearchBox onOpen={onOpen} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F095 会话搜索', () => {
  it('F095: 输入查询→结果下拉（高亮转义 + 截断标注）→点击回调', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(HITS)))
    vi.stubGlobal('fetch', fetchMock)
    const onOpen = vi.fn()
    renderBox(onOpen)

    fireEvent.change(screen.getByLabelText('搜索会话消息'), { target: { value: '阅读器' } })
    const hit = await screen.findByText('资料调研')
    expect(hit).toBeInTheDocument()
    expect(screen.getByText(/结果超过 50 条/)).toBeInTheDocument()

    // 高亮：原文里的 <b> 必须被转义为文本，不产生真实 b 元素。
    const box = document.querySelector('[data-thread-search]')!
    expect(box.querySelector('b')).toBeNull()
    expect(box.querySelectorAll('mark').length).toBeGreaterThanOrEqual(1)

    fireEvent.click(screen.getByRole('option'))
    expect(onOpen).toHaveBeenCalledWith('th-1', 4)
    const call = fetchMock.mock.calls.find((c) => String(c[0]).includes('/agent/threads/search'))
    expect(call).toBeDefined()
  })

  it('F095: 无命中空态；更短查询不发请求', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(jsonResponse({ items: [], truncated: false })),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderBox()

    // ≥2 字符才请求；空结果给诚实空态。
    fireEvent.change(screen.getByLabelText('搜索会话消息'), { target: { value: 'xy' } })
    await waitFor(() => {
      expect(screen.getByText('没有匹配的消息。')).toBeInTheDocument()
    })
    const callsAfter = fetchMock.mock.calls.length

    // 缩短到 1 字符：不再发新请求。
    fireEvent.change(screen.getByLabelText('搜索会话消息'), { target: { value: 'x' } })
    await new Promise((r) => setTimeout(r, 30))
    expect(fetchMock.mock.calls.length).toBe(callsAfter)
  })

  it('F095: highlightSnippet 纯函数——HTML 注入转义', () => {
    const html = highlightSnippet('<img src=x onerror=alert(1)>', 'img')
    expect(html).not.toContain('<img')
    // 转义后的实体上加 <mark>（先转义后高亮，注入语法不可存活）。
    expect(html).toContain('&lt;<mark>img</mark>')
  })
})
