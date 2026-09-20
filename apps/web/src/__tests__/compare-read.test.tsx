/** F016 双篇对照 —— 两实例独立渲染、失败隔离、切换保留滚动、关闭清理缓存。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CompareRead from '../components/CompareRead'
import type { EntryDetail } from '../api/types'

const getEntryMock = vi.hoisted(() => vi.fn())
vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, getEntry: getEntryMock }
})

function detail(entryRef: string): EntryDetail {
  return {
    entryRef,
    title: `标题 ${entryRef}`,
    feedTitle: '源',
    author: null,
    url: null,
    publishedAt: '2026-09-18T00:00:00Z',
    read: false,
    starred: false,
    contentHtml: `<p>${entryRef} 的正文段落。</p>`,
    contentText: '正文',
  } as unknown as EntryDetail
}

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
}

/** 网络层 mock：按 ref 决定成功/失败（这里测 CompareRead 组合行为）。 */
function mockEntryNetwork(failingRefs: string[] = []) {
  getEntryMock.mockImplementation((ref: string, signal: AbortSignal) => {
    signal.addEventListener('abort', () => {})
    if (failingRefs.includes(ref)) {
      return Promise.reject(new Error('upstream boom'))
    }
    return Promise.resolve(detail(ref))
  })
}

function renderCompare(qc: QueryClient, a: string, b: string) {
  return render(
    <QueryClientProvider client={qc}>
      <CompareRead refs={[a, b]} onClose={() => {}} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  // jsdom 无 matchMedia → useIsMobile 回退 true（移动端 A/B 模式）
})

describe('F016 双篇对照', () => {
  it('F016: 两实例独立渲染（A/B 两篇内容同时存在于 DOM）', async () => {
    const qc = makeClient()
    mockEntryNetwork()
    renderCompare(qc, 'e1.a', 'e1.b')
    expect(await screen.findByText(/e1\.a 的正文段落/)).toBeInTheDocument()
    expect(screen.getByText(/e1\.b 的正文段落/)).toBeInTheDocument()
    expect(screen.getByTestId('compare-pane-e1.a')).toBeTruthy()
    expect(screen.getByTestId('compare-pane-e1.b')).toBeTruthy()
  })

  it('F016: 一篇加载失败另一篇正常（失败隔离 + 诚实错误）', async () => {
    const qc = makeClient()
    mockEntryNetwork(['e1.bad'])
    renderCompare(qc, 'e1.bad', 'e1.ok')
    expect(await screen.findByText(/这一篇加载失败/)).toBeInTheDocument()
    expect(screen.getByText(/e1\.ok 的正文段落/)).toBeInTheDocument()
  })

  it('F016: 移动端 A/B 切换保留各自滚动位置', async () => {
    const qc = makeClient()
    mockEntryNetwork()
    renderCompare(qc, 'e1.a', 'e1.b')
    await screen.findByText(/e1\.a 的正文段落/)
    const paneA = screen.getByTestId('compare-pane-e1.a')
    const paneB = screen.getByTestId('compare-pane-e1.b')
    // jsdom 无布局，直接为两面板设置 scrollTop 并切换（hidden 不重置）
    Object.defineProperty(paneA, 'scrollTop', { value: 120, writable: true })
    Object.defineProperty(paneB, 'scrollTop', { value: 66, writable: true })
    fireEvent.click(screen.getByRole('button', { name: 'B 篇' }))
    expect(paneB.className).not.toContain('hidden')
    expect(paneA.className).toContain('hidden')
    expect(paneA.scrollTop).toBe(120) // 切换不清零（display:none 保留）
    fireEvent.click(screen.getByRole('button', { name: 'A 篇' }))
    expect(paneB.scrollTop).toBe(66)
    expect(paneB.className).toContain('hidden')
  })

  it('F016: 卸载（关闭）→ 移除本面板的两条详情缓存，不泄漏', async () => {
    const qc = makeClient()
    mockEntryNetwork()
    const { unmount } = renderCompare(qc, 'e1.a', 'e1.b')
    await screen.findByText(/e1\.a 的正文段落/)
    await screen.findByText(/e1\.a 的正文段落/)
    await waitFor(() => expect(qc.getQueryData(['entry', 'e1.a'])).toBeDefined())
    await waitFor(() => expect(qc.getQueryData(['entry', 'e1.b'])).toBeDefined())
    unmount()
    expect(qc.getQueryData(['entry', 'e1.a'])).toBeUndefined()
    expect(qc.getQueryData(['entry', 'e1.b'])).toBeUndefined()
  })
})
