/** N083 术语保护 UI —— 设置页术语本：
 * - 新建术语勾选「保留」→ POST body 带 protect:true；
 * - 列表项「保留/取消保留」→ PATCH body protect 翻转；徽标展示；
 * - 保护翻转 = glossary 写操作（服务端会推进 glossary_version，
 *   分段翻译缓存自然重算 —— 服务端语义见 test_n083_protect_terms.py）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { GlossarySection } from '../components/settings/GlossarySection'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const ITEMS = {
  items: [
    {
      id: 'glo-a',
      term: 'OpenAI',
      definition: '一家 AI 公司',
      protect: true,
      createdAt: '2026-09-01T00:00:00Z',
      updatedAt: '2026-09-01T00:00:00Z',
    },
    {
      id: 'glo-b',
      term: 'Transformer',
      definition: '一种模型架构',
      protect: false,
      createdAt: '2026-09-02T00:00:00Z',
      updatedAt: '2026-09-02T00:00:00Z',
    },
  ],
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/api/v1/glossary') && String(url).includes('limit=')) {
      return Promise.resolve(jsonResponse(ITEMS))
    }
    return Promise.resolve(jsonResponse({}))
  }))
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <GlossarySection />
    </QueryClientProvider>,
  )
}

describe('N083 术语保护（设置页）', () => {
  it('受保护术语显示「保留」徽标；未保护项提供「保留」开关', async () => {
    renderSection()
    await waitFor(() => {
      expect(screen.getByText('OpenAI')).toBeInTheDocument()
    })
    expect(screen.getByText('保留', { selector: '[data-glossary-protect-badge]' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '取消保留' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保留' })).toBeInTheDocument()
  })

  it('翻转保护：PATCH body 带 protect（全量替换 term+definition+protect）', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('limit=')) return Promise.resolve(jsonResponse(ITEMS))
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderSection()
    await waitFor(() => {
      expect(screen.getByText('Transformer')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: '保留' }))
    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/api/v1/glossary/glo-b'))
      expect(patch).toBeDefined()
      const patchInit = (patch as Array<unknown>)[1] as RequestInit
      expect(patchInit.method).toBe('PATCH')
      expect(JSON.parse(String(patchInit.body))).toEqual({
        term: 'Transformer',
        definition: '一种模型架构',
        protect: true,
      })
    })
  })

  it('新建术语勾选「保留」→ POST body 带 protect:true', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('limit=')) return Promise.resolve(jsonResponse(ITEMS))
      return Promise.resolve(
        jsonResponse({
          id: 'glo-c',
          term: 'RAG',
          definition: '检索增强生成',
          protect: true,
        }),
      )
    })
    vi.stubGlobal('fetch', fetchMock)
    renderSection()
    await waitFor(() => {
      expect(screen.getByText('OpenAI')).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText('术语'), { target: { value: 'RAG' } })
    fireEvent.change(screen.getByLabelText('解释'), { target: { value: '检索增强生成' } })
    fireEvent.click(screen.getByLabelText('保留（翻译时保持原文）'))
    fireEvent.click(screen.getByRole('button', { name: '添加术语' }))

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(([url, init]) =>
        String(url).endsWith('/api/v1/glossary') && (init as RequestInit).method === 'POST',
      )
      expect(post).toBeDefined()
      const postInit = (post as Array<unknown>)[1] as RequestInit
      expect(JSON.parse(String(postInit.body))).toEqual({
        term: 'RAG',
        definition: '检索增强生成',
        protect: true,
      })
    })
  })
})
