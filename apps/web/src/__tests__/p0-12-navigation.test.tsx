/** P0-12 wave 1 — 导航诚实性 + 设置深链测试。
 *
 * - 侧栏「API 来源」「邮件简报」不再是 PlannedItem：真实入口 →
 *   requestOpenSettings(category) → 设置壳打开并直达对应分类
 *   （桌面 Modal 与移动全屏页共用同一深链契约）；
 * - 未知分类 id 安全降级为通用分类；
 * - Settings「工作区」分类不再自称占位（Agent 工作台/工作区已上线）；
 * - PlannedItem（RAG 索引）以真 disabled button 呈现并诚实说明。
 */

import { act, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import SettingsModal from '../components/settings/SettingsModal'
import MobileSettingsScreen from '../components/MobileSettingsScreen'
import SettingsButton from '../components/SettingsButton'
import { requestOpenSettings } from '../components/settings/settings-bridge'
import type { SettingsOpenDetail } from '../components/settings/settings-bridge'

function withQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
}

function stubFetchErrorEnvelope(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(async () =>
      new Response(JSON.stringify({ error: { type: 'not_found', message: 'x' } }), {
        status: 404,
        headers: { 'content-type': 'application/json' },
      }),
    ),
  )
}

describe('设置深链（P0-12）', () => {
  it('SettingsModal：openCategory=api-sources → 直达 API 来源分类（导航高亮）', () => {
    stubFetchErrorEnvelope()
    render(
      withQueryClient(
        <SettingsModal open onClose={vi.fn()} openCategory={{ category: 'api-sources', seq: 1 }} />,
      ),
    )
    expect(screen.getByRole('heading', { level: 2, name: 'API 来源' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /API 来源/ })).toHaveAttribute('aria-current', 'true')
    vi.unstubAllGlobals()
  })

  it('SettingsModal：未知分类 id 安全降级为通用（不渲染空分类页）', () => {
    stubFetchErrorEnvelope()
    render(
      withQueryClient(
        <SettingsModal open onClose={vi.fn()} openCategory={{ category: 'not-a-category', seq: 1 }} />,
      ),
    )
    expect(screen.getByRole('heading', { level: 2, name: '通用' })).toBeInTheDocument()
    vi.unstubAllGlobals()
  })

  it('MobileSettingsScreen：openCategory=mail → 直达邮件简报子页', () => {
    stubFetchErrorEnvelope()
    // jsdom 无 matchMedia → useIsMobile=true，本组件可渲染
    render(
      withQueryClient(
        <MobileSettingsScreen
          open
          onClose={vi.fn()}
          openCategory={{ category: 'mail', seq: 1 }}
        />,
      ),
    )
    expect(screen.getByRole('heading', { level: 2, name: '邮件简报' })).toBeInTheDocument()
    vi.unstubAllGlobals()
  })

  it('端到端：requestOpenSettings 深链 → SettingsButton 拉起设置壳并直达分类', async () => {
    stubFetchErrorEnvelope()
    render(withQueryClient(<SettingsButton />))
    act(() => {
      requestOpenSettings('api-sources')
    })
    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 2, name: 'API 来源' })).toBeInTheDocument()
    })
    vi.unstubAllGlobals()
  })
})

describe('设置「工作区」分类文案诚实性（P0-12）', () => {
  it('不再自称占位/规划中；如实指向 Agent 工作台与工作区入口', () => {
    stubFetchErrorEnvelope()
    const openCategory: SettingsOpenDetail = { category: 'workspace', seq: 1 }
    render(withQueryClient(<MobileSettingsScreen open onClose={vi.fn()} openCategory={openCategory} />))
    expect(screen.getByText('知识工作台')).toBeInTheDocument()
    expect(screen.getByText('已上线')).toBeInTheDocument()
    expect(screen.getByText(/Agent 工作台/)).toBeInTheDocument()
    expect(screen.queryByText(/本页为占位/)).toBeNull()
    expect(screen.queryByText('规划中')).toBeNull()
    vi.unstubAllGlobals()
  })
})
