/** F078 UI — 同义词控件：扩展开关持久化（默认开）+ 管理对话框增删。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SynonymsControls, readExpandSynonyms } from '../components/SynonymsControls'
import { useState } from 'react'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function Harness() {
  const [expanded, setExpanded] = useState(readExpandSynonyms())
  return (
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
      <SynonymsControls expanded={expanded} onToggle={setExpanded} />
      <span data-testid="state">{expanded ? 'on' : 'off'}</span>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F078 同义词控件', () => {
  it('F078: 默认扩展开；关闭立即生效并持久化；重新挂载仍是关', async () => {
    render(<Harness />)
    const toggle = screen.getByRole('switch', { name: '同义词扩展' })
    expect(toggle).toBeChecked()
    expect(screen.getByTestId('state').textContent).toBe('on')
    fireEvent.click(toggle)
    expect(screen.getByTestId('state').textContent).toBe('off')
    expect(localStorage.getItem('lumirss-synonym-expand')).toBe('false')
    // 重新挂载：读取持久化 → off
    const second = render(<Harness />)
    expect(screen.getAllByTestId('state').some((el) => el.textContent === 'off')).toBe(true)
    second.unmount()
  })

  it('F078: 管理对话框：列表渲染 + 添加调用 POST + 删除调用 DELETE', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        if (method === 'POST' && url === '/api/v1/search/synonyms') {
          return Promise.resolve(
            jsonResponse({ id: 's2', term: 'LLM', expansions: ['大模型'], enabled: true }),
          )
        }
        if (method === 'DELETE') {
          return new Response(null, { status: 204 })
        }
        return Promise.resolve(
          jsonResponse({ items: [{ id: 's1', term: 'rss', expansions: ['feed'], enabled: true }] }),
        )
      })
    vi.stubGlobal('fetch', fetchMock)
    render(<Harness />)

    fireEvent.click(screen.getByRole('button', { name: '同义词' }))
    expect(await screen.findByText('rss')).toBeInTheDocument()
    expect(screen.getByText(/→ feed/)).toBeInTheDocument()

    // 添加：词 + 扩展词（| 分隔）
    fireEvent.change(screen.getByLabelText('同义词词'), { target: { value: 'LLM' } })
    fireEvent.change(screen.getByLabelText('扩展词'), { target: { value: '大模型 | LLM2' } })
    fireEvent.click(screen.getByRole('button', { name: '添加' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/search/synonyms',
        expect.objectContaining({ method: 'POST' }),
      )
    })
    const body = JSON.parse(
      (fetchMock.mock.calls.find((c) => (c[1] as RequestInit)?.method === 'POST')?.[1] as RequestInit).body as string,
    )
    expect(body.term).toBe('LLM')
    expect(body.expansions).toEqual(['大模型', 'LLM2'])

    // 删除
    fireEvent.click(screen.getAllByRole('button', { name: '删除' })[0])
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/search/synonyms/s1',
        expect.objectContaining({ method: 'DELETE' }),
      )
    })
  })
})
