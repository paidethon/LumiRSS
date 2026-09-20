/** F027 摘要版本 —— 选择器/切换/对比上一版。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReaderSummary from '../components/ReaderSummary'

const ENTRY_REF = 'e1.aWVtLTM'

const VERSIONS = [
  { versionId: 'sv-1', summary: '第一版摘要。', provider: 'openai', model: 'model-a', createdAt: '2026-09-18T08:00:00Z' },
  { versionId: 'sv-2', summary: '第一版摘要。\n新增了第二行。', provider: 'openai', model: 'model-a', createdAt: '2026-09-19T08:00:00Z' },
]

let current = {
  status: 'success',
  summary: VERSIONS[1].summary,
  provider: 'openai',
  model: 'model-a',
  promptVersion: 'v',
  language: 'zh-CN',
  generatedAt: '2026-09-19T08:00:00Z',
  failureType: null,
  cached: false,
  inputChars: 1234,
  truncated: false,
  versions: VERSIONS,
  activeVersionId: null as string | null,
}

const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input)
  const method = init?.method ?? 'GET'
  if (method === 'GET' && url.includes('/summary')) {
    return Promise.resolve(new Response(JSON.stringify(current), { status: 200 }))
  }
  if (method === 'POST' && url.includes('/versions/sv-1/activate')) {
    current = { ...current, summary: VERSIONS[0].summary, activeVersionId: 'sv-1' }
    return Promise.resolve(new Response(JSON.stringify(current), { status: 200 }))
  }
  return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }))
})

function renderCard() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <ReaderSummary entryRef={ENTRY_REF} articleText="正文" />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  fetchMock.mockClear()
  current = {
    status: 'success',
    summary: VERSIONS[1].summary,
    provider: 'openai',
    model: 'model-a',
    promptVersion: 'v',
    language: 'zh-CN',
    generatedAt: '2026-09-19T08:00:00Z',
    failureType: null,
    cached: false,
    inputChars: 1234,
    truncated: false,
    versions: VERSIONS,
    activeVersionId: null,
  }
  vi.stubGlobal('fetch', fetchMock)
})

describe('F027 AI 结果版本', () => {
  it('F027: 版本选择器（时间+模型）与共 N 版', async () => {
    renderCard()
    expect(await screen.findByText(/共 2 版/)).toBeInTheDocument()
    expect(screen.getAllByText(/model-a/).length).toBeGreaterThan(0)
  })

  it('F027: 切换版本发出 activate 请求', async () => {
    renderCard()
    await screen.findByText(/共 2 版/)
    fireEvent.change(screen.getByLabelText('摘要版本'), { target: { value: 'sv-1' } })
    fireEvent.click(screen.getByRole('button', { name: '切换到此版本' }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/versions/sv-1/activate'))).toBe(true)
    })
  })

  it('F027: 对比上一版显示增删行', async () => {
    renderCard()
    await screen.findByText(/共 2 版/)
    fireEvent.click(screen.getByRole('button', { name: /对比上一版/ }))
    expect(await screen.findByText('上一版')).toBeInTheDocument()
    expect(screen.getAllByText('新增了第二行。').length).toBeGreaterThan(0)
  })
})
