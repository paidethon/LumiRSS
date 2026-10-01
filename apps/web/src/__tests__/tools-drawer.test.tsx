/** R11 方案 B — ToolsDrawer 行为证明（图2 九入口中抽屉内六项）。
 *
 * - 唯一 DetailDrawer：标题「工具」；分组 tab 阅读/整理/共读（Tabs 原语）；
 * - 阅读组列出 阅读预算/今日必读/阅读路径/阅读决策，整理组列出
 *   积压整理，共读组列出 共读空间——一个不删；
 * - 二级视图：点击工具 → 面板在抽屉内展开（返回栈在抽屉内：返回按钮
 *   与面板自身「关闭」都回工具列表，不关抽屉）；
 * - 从面板内打开文章（阅读路径「恢复」）= 交给宿主 onOpenEntry 并
 *   整体收起抽屉（正文接管）；
 * - 空组语义：三组都有工具，无空 tab。
 *
 * 网络：本套件只挂载零请求面板（阅读预算 / 阅读路径设备本地 / 积压
 * 整理折叠态）；fetch stub 恒抛错——任何意外请求都会让断言显形。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import ToolsDrawer from '../components/ToolsDrawer'

function withProviders(ui: ReactNode): ReactNode {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

function renderDrawer(
  overrides: Partial<{ onClose: () => void; onOpenEntry: (ref: string) => void }> = {},
): void {
  render(
    withProviders(
      <ToolsDrawer
        open
        onClose={overrides.onClose ?? (() => {})}
        onOpenEntry={overrides.onOpenEntry}
        budgetCandidates={[{ entryRef: 'e1.a', title: '文章 A', text: '摘要 A' }]}
      />,
    ),
  )
}

/** 断言当前在工具列表层（二级视图未展开；id 需与当前 tab 的工具匹配）。 */
async function expectToolListVisible(toolId = 'budget'): Promise<void> {
  await waitFor(() => {
    expect(screen.getByTestId(`tools-drawer-item-${toolId}`)).toBeInTheDocument()
  })
  expect(screen.queryByTestId('tools-drawer-secondary')).toBeNull()
}

beforeEach(() => {
  window.localStorage.clear()
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      throw new Error(`unexpected fetch: ${String(input)}`)
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ToolsDrawer — 分组与九入口归属', () => {
  it('默认阅读组：四个工具（阅读预算/今日必读/阅读路径/阅读决策）各带一句说明', () => {
    renderDrawer()
    expect(screen.getByRole('tab', { name: '阅读' })).toHaveAttribute('aria-selected', 'true')
    for (const id of ['budget', 'queue', 'path', 'decisions']) {
      expect(screen.getByTestId(`tools-drawer-item-${id}`)).toBeInTheDocument()
    }
    expect(screen.getByTestId('tools-drawer-item-budget')).toHaveTextContent('阅读预算')
    expect(screen.getByTestId('tools-drawer-item-budget')).toHaveTextContent('临时阅读清单')
    expect(screen.getByTestId('tools-drawer-item-queue')).toHaveTextContent('今日必读')
    expect(screen.getByTestId('tools-drawer-item-path')).toHaveTextContent('阅读路径')
    expect(screen.getByTestId('tools-drawer-item-decisions')).toHaveTextContent('阅读决策')
  })

  it('整理组：积压整理；共读组：共读空间（三组 tab 全部非空）', () => {
    renderDrawer()
    fireEvent.click(screen.getByRole('tab', { name: '整理' }))
    expect(screen.getByTestId('tools-drawer-item-backlog')).toHaveTextContent('积压整理')
    expect(screen.queryByTestId('tools-drawer-item-budget')).toBeNull()

    fireEvent.click(screen.getByRole('tab', { name: '共读' }))
    expect(screen.getByTestId('tools-drawer-item-space')).toHaveTextContent('共读空间')
  })
})

describe('ToolsDrawer — 面板内二级视图（返回栈在抽屉内）', () => {
  it('点击工具 → 面板展开 + 返回按钮；返回回工具列表（抽屉不关）', async () => {
    const onClose = vi.fn()
    renderDrawer({ onClose })
    fireEvent.click(screen.getByRole('tab', { name: '整理' }))
    fireEvent.click(screen.getByTestId('tools-drawer-item-backlog'))

    // 二级视图：返回 + 面板本体（积压整理面板文案；懒 chunk 需等一拍）
    expect(await screen.findByTestId('tools-drawer-secondary')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '返回工具列表' })).toBeInTheDocument()
    expect(await screen.findByText(/积压整理（批量标为已读/)).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: '返回工具列表' }))
    await expectToolListVisible('backlog')
    expect(onClose).not.toHaveBeenCalled()
  })

  it('面板自身「关闭」= 回工具列表（不关抽屉）', async () => {
    renderDrawer()
    fireEvent.click(screen.getByTestId('tools-drawer-item-budget'))
    // 阅读预算面板挂载（零请求）；其关闭按钮在面板 chrome 内
    fireEvent.click(await screen.findByRole('button', { name: '关闭阅读预算' }))
    await expectToolListVisible()
  })

  it('从面板内打开文章（阅读路径「恢复」）→ onOpenEntry + 抽屉整体收起', async () => {
    // N050 设备本地：预置一条足迹（rss:e1.a）
    window.localStorage.setItem(
      'lumi-reading-path',
      JSON.stringify({
        enabled: true,
        entries: [{ ref: 'rss:e1.a', title: '文章 A', at: new Date().toISOString() }],
      }),
    )
    const onClose = vi.fn()
    const onOpenEntry = vi.fn()
    renderDrawer({ onClose, onOpenEntry })

    fireEvent.click(screen.getByTestId('tools-drawer-item-path'))
    fireEvent.click(await screen.findByRole('button', { name: /恢复/ }))
    expect(onOpenEntry).toHaveBeenCalledWith('e1.a')
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})

describe('ToolsDrawer — 键盘与浮层契约', () => {
  it('三组 tab 完整、点击可切换（方向键 roving 由 Tabs 原语既有测试覆盖）', () => {
    renderDrawer()
    const tablist = screen.getByRole('tablist', { name: '工具分组' })
    expect(within(tablist).getAllByRole('tab')).toHaveLength(3)
    fireEvent.click(screen.getByRole('tab', { name: '整理' }))
    expect(screen.getByRole('tab', { name: '整理' })).toHaveAttribute('aria-selected', 'true')
    fireEvent.click(screen.getByRole('tab', { name: '共读' }))
    expect(screen.getByRole('tab', { name: '共读' })).toHaveAttribute('aria-selected', 'true')
  })
})
