/** F028 术语表导入导出（GlossarySection 面板交互）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { GlossarySection } from '../components/settings/GlossarySection'

const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input)
  const method = init?.method ?? 'GET'
  if (method === 'GET' && url.includes('/api/v1/glossary?') === false && url.endsWith('/glossary')) {
    return Promise.resolve(new Response(JSON.stringify({ items: [] }), { status: 200 }))
  }
  if (method === 'GET' && url.includes('/glossary/export')) {
    return Promise.resolve(
      new Response(JSON.stringify({ terms: [{ term: 'LLM', translation: '大语言模型' }] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
  }
  if (method === 'POST' && url.includes('/glossary/import')) {
    return Promise.resolve(
      new Response(JSON.stringify({ imported: 2, skipped: 1, overwritten: 0, errors: [] }), { status: 200 }),
    )
  }
  return Promise.resolve(new Response(JSON.stringify({ items: [] }), { status: 200 }))
})

function renderSection() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <GlossarySection />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  fetchMock.mockClear()
  vi.stubGlobal('fetch', fetchMock)
  URL.createObjectURL = vi.fn(() => 'blob:x')
  URL.revokeObjectURL = vi.fn()
})

describe('F028 术语表批量导入导出', () => {
  it('F028: 打开导入框 → 粘贴 JSON 预览条数 → skip 导入展示结果', async () => {
    renderSection()
    const openBtn = await screen.findAllByRole('button', { name: '导入' }); fireEvent.click(openBtn[openBtn.length - 1])
    fireEvent.change(screen.getByLabelText('粘贴术语 JSON'), {
      target: {
        value: JSON.stringify({
          terms: [
            { term: 'LLM', translation: '大语言模型' },
            { term: 'RAG', translation: '检索增强生成' },
            { term: 'MoE', translation: '混合专家' },
          ],
        }),
      },
    })
    expect(await screen.findByText(/共 3 条可导入/)).toBeInTheDocument()
    const submitBtn = screen.getAllByRole('button', { name: '导入' }); fireEvent.click(submitBtn[submitBtn.length - 1])
    expect(await screen.findByText(/导入 2 · 跳过 1 · 覆盖 0/)).toBeInTheDocument()
    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        ([url, init]) => String(url).includes('/glossary/import') && (init as RequestInit).method === 'POST',
      )
      expect(JSON.parse(String((post as unknown as [string, RequestInit])[1].body)).mode).toBe('skip')
    })
  })

  it('F028: 导出发起下载请求', async () => {
    renderSection()
    fireEvent.click(await screen.findByRole('button', { name: '导出' }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/glossary/export'))).toBe(true)
    })
  })
})
