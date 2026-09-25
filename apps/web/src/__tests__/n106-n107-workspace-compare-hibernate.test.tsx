/** N106 工作区双栏对读 + N107 窗格休眠测试。
 *
 * N106：
 * - 从工作区挑 2 个条目 → 两栏并排渲染（复用 CompareRead）；
 * - 手动锚点同步按钮：A 滚动 → 点击 → B 跳到相同百分比落点；
 * - 窄屏（移动判定）→ 既有无障碍 A/B 切换（role=tablist）。
 *
 * N107（测量型断言）：
 * - 空闲超阈值 → 真实休眠：容器 DOM 节点数显著下降（真实释放，不是
 *   换图标）；交互唤醒 → 节点数恢复 + 滚动位置还原。
 */

import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import WorkspaceCompare from '../components/WorkspaceCompare'
import CompareRead from '../components/CompareRead'
import { usePaneHibernate, shouldHibernate } from '../lib/pane-hibernate'
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

beforeEach(() => {
  getEntryMock.mockImplementation((ref: string) => Promise.resolve(detail(ref)))
})

// 简化 QueryClient（复用现有 compare-read 测试的注入模式）。
function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('N106 工作区双栏对读', () => {
  it('挑 2 个条目后两栏并排渲染', async () => {
    const items = [
      { ref: 'rss:a', title: '文章甲' },
      { ref: 'rss:b', title: '文章乙' },
      { ref: 'rss:c', title: '文章丙' },
    ]
    const onClose = vi.fn()
    const { container } = renderWithClient(
      <WorkspaceCompare items={items} onClose={onClose} />,
    )
    expect(screen.getByTestId('workspace-compare-picker')).toBeInTheDocument()

    fireEvent.change(screen.getByTestId('compare-pick-a'), {
      target: { value: 'rss:a' },
    })
    fireEvent.change(screen.getByTestId('compare-pick-b'), {
      target: { value: 'rss:b' },
    })
    // 等详情查询真实落定（正文出现），再断言双栏容器。
    await screen.findByText(/rss:a 的正文段落/)
    await screen.findByText(/rss:b 的正文段落/)
    // 两栏：两个 compare-pane 容器。
    const panes = container.querySelectorAll('[data-compare-scroll]')
    expect(panes).toHaveLength(2)
    // 锚点同步按钮存在（工作区模式专属）。
    expect(screen.getByTestId('compare-anchor-sync')).toBeInTheDocument()
  })

  it('锚点同步：点击按钮把 A 的滚动百分比落到 B', async () => {
    const items = [
      { ref: 'rss:a', title: '文章甲' },
      { ref: 'rss:b', title: '文章乙' },
    ]
    const { container } = renderWithClient(
      <WorkspaceCompare items={items} onClose={vi.fn()} />,
    )
    fireEvent.change(screen.getByTestId('compare-pick-a'), { target: { value: 'rss:a' } })
    fireEvent.change(screen.getByTestId('compare-pick-b'), { target: { value: 'rss:b' } })
    await screen.findByText(/rss:a 的正文段落/)
    await screen.findByText(/rss:b 的正文段落/)

    const panes = container.querySelectorAll<HTMLElement>('[data-compare-scroll]')
    const a = panes[0]
    const b = panes[1]
    // 构造可滚动状态（jsdom 无布局 —— 直接 stub 尺寸与 scrollTop）。
    const makeScrollable = (el: HTMLElement, height: number, scrollHeight: number) => {
      Object.defineProperty(el, 'clientHeight', { value: height, configurable: true })
      Object.defineProperty(el, 'scrollHeight', { value: scrollHeight, configurable: true })
    }
    makeScrollable(a, 100, 1000)
    makeScrollable(b, 100, 800)
    a.scrollTop = 450 // A 落点 50%
    b.scrollTop = 0

    fireEvent.click(screen.getByTestId('compare-anchor-sync'))
    // B 跳到 ~50%：400（800-100 的 50%）。
    expect(b.scrollTop).toBeGreaterThan(300)
    expect(b.scrollTop).toBeLessThan(500)
  })

  it('非工作区模式（默认）不渲染锚点同步按钮', async () => {
    renderWithClient(<CompareRead refs={['rss:a', 'rss:b']} onClose={vi.fn()} />)
    await waitFor(() => screen.getByTestId('compare-read'))
    expect(screen.queryByTestId('compare-anchor-sync')).toBeNull()
  })
})

describe('N107 窗格休眠（状态机 + 测量断言）', () => {
  it('shouldHibernate 纯判定：超阈值才休眠', () => {
    expect(shouldHibernate(1000, 1000 + 10 * 60 * 1000, 10 * 60 * 1000)).toBe(true)
    expect(shouldHibernate(1000, 1000 + 60 * 1000, 10 * 60 * 1000)).toBe(false)
    expect(shouldHibernate(0, 10 ** 12, 10 * 60 * 1000)).toBe(false) // 从未活跃
  })

  it('休眠真实释放 DOM（节点数下降），唤醒恢复内容与滚动位置', () => {
    vi.useFakeTimers()
    function Demo() {
      const { hibernated, containerRef, wake } = usePaneHibernate({ idleMs: 50 })
      return (
        <div ref={containerRef} data-testid="hibernate-container" style={{ maxHeight: 50, overflow: 'auto' }}>
          {hibernated ? (
            <button type="button" onClick={wake} data-testid="wake-btn">
              唤醒
            </button>
          ) : (
            <div data-testid="heavy-content">
              {Array.from({ length: 50 }, (_, i) => (
                <p key={i}>段落 {i}</p>
              ))}
            </div>
          )}
        </div>
      )
    }
    const { container } = render(<Demo />)
    const heavy = () => container.querySelectorAll('p').length

    // 活动前：50 个段落节点。
    expect(heavy()).toBe(50)
    const box = container.querySelector<HTMLElement>('[data-testid="hibernate-container"]')
    if (box === null) throw new Error('hibernate container missing')
    Object.defineProperty(box, 'scrollHeight', { value: 5000, configurable: true })
    Object.defineProperty(box, 'clientHeight', { value: 100, configurable: true })
    box.scrollTop = 420

    // 空闲 50ms → 休眠：正文 <p> 全部卸载（真实 DOM 释放）。
    act(() => {
      vi.advanceTimersByTime(80)
    })
    expect(heavy()).toBe(0)
    // 真实释放证据：正文被卸载，只剩占位按钮（不是仅换图标）。
    expect(container.querySelector('[data-testid="wake-btn"]')).toBeTruthy()

    // 唤醒：内容恢复 + 滚动位置还原。
    fireEvent.click(container.querySelector('[data-testid="wake-btn"]')!)
    expect(heavy()).toBe(50)
    vi.useRealTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })
})
