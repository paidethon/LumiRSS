/** M1 布局契约 — Agent 工作台全宽回归测试。
 *
 * 选择 agent section 后：
 * - Agent 工作台挂载（会话列表空态可见）；
 * - Reader 空态（选择一篇文章开始阅读 / 正文将在右侧展示）不在 DOM——
 *   这是用户报告的「Agent 只占左半边、右侧 Reader 空态占满」缺陷；
 * - Timeline（EntryList）与 Reader 均不挂载：无 /entries 时间线请求；
 * - Sidebar（主导航）保留；
 * - 返回 home：Timeline / Reader 占位恢复，时间线请求重新发生。
 *
 * graph 与 agent 同属 FULL_WIDTH_SECTIONS，本文件一并覆盖 graph 挂载。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../App'
import { useReaderUi } from '../store/reader-ui'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

/** 记录 /entries 相关请求；其余端点按前缀给最小合法响应。 */
function mockApi() {
  const entryCalls: string[] = []
  const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/entries')) {
      entryCalls.push(url)
      return jsonResponse({ items: [], nextCursor: null })
    }
    if (url.includes('/agent/threads')) return jsonResponse({ items: [] })
    if (url.includes('/rag/status')) {
      return jsonResponse({ enabled: false, available: false, detail: null })
    }
    if (url.includes('/feeds')) return jsonResponse([])
    if (url.includes('/tags')) return jsonResponse({ items: [] })
    return jsonResponse({})
  })
  return { fetchMock, entryCalls }
}

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useReaderUi.setState({
    view: 'all',
    scope: { kind: 'all' },
    selectedEntryRef: null,
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('M1：Agent 工作台全宽布局契约', () => {
  it('agent section：工作台挂载，Reader 空态与 Timeline 不渲染，无 entries 请求', async () => {
    const { fetchMock, entryCalls } = mockApi()
    vi.stubGlobal('fetch', fetchMock)
    // 以 agent 为初始 section 挂载：全程不发生 entries 时间线/详情请求
    useReaderUi.setState({ section: 'agent', selectedEntryRef: null })
    renderApp()

    // 工作台空态可见（会话列表区；移动+桌面双实例为既有渲染模式，可见性单实例）
    expect((await screen.findAllByLabelText('会话列表'))[0]).toBeInTheDocument()

    // 用户报告的缺陷：Reader 空态不得存在
    expect(screen.queryByText('选择一篇文章开始阅读')).not.toBeInTheDocument()
    expect(screen.queryByText('正文将在右侧展示；也可以用 ← 返回列表。')).not.toBeInTheDocument()

    // Timeline（EntryList）不挂载：无时间线/详情 entries 请求
    expect(entryCalls).toEqual([])

    // 全宽区域存在且独占主区：Timeline|Reader 分隔条不渲染
    const fullwidthRegions = screen.getAllByLabelText('Agent 工作台')
    expect(fullwidthRegions.length).toBeGreaterThan(0)
    expect(screen.queryByRole('separator', { name: '文章列表宽度' })).not.toBeInTheDocument()

    // 全局导航保留
    expect(screen.getByRole('navigation', { name: '主导航' })).toBeInTheDocument()
  })

  it('graph section：全宽挂载，Reader 空态不存在', async () => {
    const { fetchMock } = mockApi()
    vi.stubGlobal('fetch', fetchMock)
    renderApp()

    act(() => {
      useReaderUi.getState().selectSection('graph')
    })

    expect((await screen.findAllByLabelText('标签与图谱'))[0]).toBeInTheDocument()
    expect(screen.queryByText('选择一篇文章开始阅读')).not.toBeInTheDocument()
  })

  it('agent → home 往返：Reader 占位与时间线恢复', async () => {
    const { fetchMock, entryCalls } = mockApi()
    vi.stubGlobal('fetch', fetchMock)
    renderApp()

    act(() => {
      useReaderUi.getState().selectSection('agent')
    })
    await screen.findAllByLabelText('会话列表')
    expect(screen.queryByText('选择一篇文章开始阅读')).not.toBeInTheDocument()

    act(() => {
      useReaderUi.getState().selectSection('home')
    })

    // 回到 RSS：Reader 空态恢复（home 无选中文章）
    await waitFor(() => {
      expect(screen.getByText('选择一篇文章开始阅读')).toBeInTheDocument()
    })
    // 时间线重新拉取
    await waitFor(() => {
      expect(entryCalls.length).toBeGreaterThan(0)
    })
  })
})
