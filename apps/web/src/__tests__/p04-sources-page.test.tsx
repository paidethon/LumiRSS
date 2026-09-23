/** P04 — 统一来源管理页（SourcesPage）+ 底栏/侧栏「来源」入口。
 *
 * 统一 vi.mock('../api/client')（保留其余真实导出）：mock listSources
 * （GET /api/v1/sources 注册表投影——字段只有 id/type/label/enabled/
 * summary/lastSuccessAt/lastError，断言不发明状态）与 getRssHubRoutes
 * （添加来源 RSSHub 深链的路由目录）。覆盖：
 * - 六类来源分组渲染 + 行内诚实健康面（已停用 / 最近成功 / 最近错误）；
 * - 每类管理深链：rss→订阅中心、inbox/obsidian→section、
 *   api_source/newsletter→设置直达分类、rsshub→添加来源 RssHubTab；
 * - 「添加来源」按钮（默认 RSS/Atom 模式）；
 * - 加载 / 空 / 错误重试状态；
 * - MobileTabBar「来源」tab（P04 替换原「订阅」）；桌面侧栏「来源」
 *   入口（RSS 订阅行保留）。
 */

import { fireEvent, render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SourcesPage from '../components/pages/SourcesPage'
import MobileTabBar from '../components/MobileTabBar'
import Sidebar from '../components/Sidebar'
import { useReaderUi } from '../store/reader-ui'
import { onOpenSettingsRequest } from '../components/settings/settings-bridge'
import type { SourceRegistryResponse } from '../api/types'

const mocks = vi.hoisted(() => ({
  listSources: vi.fn<() => Promise<SourceRegistryResponse>>(),
  getRssHubRoutes: vi.fn<() => Promise<{ configured: boolean; routes: Array<{ id: string; title: string; description: string; parameters: never[] }> }>>(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    listSources: mocks.listSources,
    getRssHubRoutes: mocks.getRssHubRoutes,
  }
})

function withProviders(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

/** 与 services/bff sources.py 的投影形状逐字段一致（不发明字段）。 */
const SOURCE_OK: SourceRegistryResponse = {
  generatedAt: '2026-09-23T00:00:00Z',
  sources: [
    {
      id: 'freshrss',
      type: 'rss',
      label: 'FreshRSS',
      enabled: true,
      summary: 'RSS/Atom 订阅、条目、已读/收藏的唯一真源',
      lastSuccessAt: null,
      lastError: null,
    },
    {
      id: 'rsshub',
      type: 'rsshub',
      label: 'RSSHub',
      enabled: true,
      summary: '非 RSS 来源的上游生成器（经 FreshRSS 订阅）',
      lastSuccessAt: null,
      lastError: null,
    },
    {
      id: 'api-source:u1',
      type: 'api_source',
      label: 'GitHub Trending',
      enabled: true,
      summary: 'JMESPath → Atom → FreshRSS（条目归 FreshRSS）',
      lastSuccessAt: '2026-09-20T08:00:00Z',
      lastError: null,
    },
    {
      id: 'mail:m1',
      type: 'newsletter',
      label: '周报邮件桥',
      enabled: true,
      summary: '邮件桥：webhook/IMAP → 摘要 → Atom → FreshRSS',
      lastSuccessAt: null,
      lastError: null,
    },
    {
      id: 'obsidian',
      type: 'obsidian',
      label: 'Obsidian vault',
      enabled: false,
      summary: '只读单向投影；vault 始终是真源',
      lastSuccessAt: null,
      lastError: 'vault 路径不可读',
    },
    {
      id: 'inbox:i1',
      type: 'inbox',
      label: '推送脚本',
      enabled: true,
      summary: '推送式 JSON 收件连接器（api_item 内容归 Lumi）',
      lastSuccessAt: '2026-09-21T10:00:00Z',
      lastError: null,
    },
  ],
}

beforeEach(() => {
  useReaderUi.setState({
    section: 'home',
    scope: { kind: 'all' },
    view: 'all',
    selectedEntryRef: null,
    mobileSidebarOpen: false,
  })
  mocks.listSources.mockReset()
  mocks.getRssHubRoutes.mockReset()
})

describe('SourcesPage 分组渲染（P04 AC-a）', () => {
  it('六类来源按类型分组渲染，行内只渲染 API 真实提供的健康面', async () => {
    mocks.listSources.mockResolvedValue(SOURCE_OK)
    render(withProviders(<SourcesPage />))

    const rss = await screen.findByRole('region', { name: 'RSS 订阅' })
    expect(within(rss).getByText('FreshRSS')).toBeInTheDocument()

    expect(screen.getByRole('region', { name: 'RSSHub 路由' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'API 来源' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '邮件桥' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '收件箱' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Obsidian' })).toBeInTheDocument()

    const apiGroup = screen.getByRole('region', { name: 'API 来源' })
    expect(within(apiGroup).getByText('GitHub Trending')).toBeInTheDocument()
    // lastSuccessAt → 最近成功（格式化自 API 字段，非发明状态）
    expect(within(apiGroup).getByText(/最近成功：/)).toBeInTheDocument()

    // enabled=false → 已停用；lastError → 最近错误（role=alert）
    const obsidian = screen.getByRole('region', { name: 'Obsidian' })
    expect(within(obsidian).getByText('已停用')).toBeInTheDocument()
    expect(
      within(obsidian).getByText('最近错误：vault 路径不可读'),
    ).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(
      '最近错误：vault 路径不可读',
    )

    // 每行都有「管理」深链按钮（44px 目标）
    expect(within(rss).getByRole('button', { name: '管理' })).toBeInTheDocument()
  })

  it('注册表出现未知类型时按原类型渲染（无深链），不假设类型集合封闭', async () => {
    mocks.listSources.mockResolvedValue({
      generatedAt: '2026-09-23T00:00:00Z',
      sources: [
        {
          id: 'future:x',
          type: 'future_type',
          label: '未来来源',
          enabled: true,
          summary: null,
          lastSuccessAt: null,
          lastError: null,
        },
      ],
    })
    render(withProviders(<SourcesPage />))
    const future = await screen.findByRole('region', { name: 'future_type' })
    expect(within(future).getByText('未来来源')).toBeInTheDocument()
    expect(within(future).queryByRole('button', { name: '管理' })).toBeNull()
  })

  it('空注册表 → 诚实空态', async () => {
    mocks.listSources.mockResolvedValue({
      sources: [],
      generatedAt: '2026-09-23T00:00:00Z',
    })
    render(withProviders(<SourcesPage />))
    expect(await screen.findByText('暂无来源')).toBeInTheDocument()
  })

  it('加载失败 → 错误态 + 重试成功后渲染分组', async () => {
    mocks.listSources.mockRejectedValueOnce(new Error('BFF 不可达'))
    render(withProviders(<SourcesPage />))
    expect(await screen.findByText('来源列表加载失败')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('BFF 不可达')

    mocks.listSources.mockResolvedValue(SOURCE_OK)
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(
      await screen.findByRole('region', { name: 'RSS 订阅' }),
    ).toBeInTheDocument()
  })
})

describe('SourcesPage 管理深链（P04 AC-b）', () => {
  it('rss → 订阅中心 section；inbox / obsidian → 对应 section', async () => {
    mocks.listSources.mockResolvedValue(SOURCE_OK)
    render(withProviders(<SourcesPage />))
    await screen.findByRole('region', { name: 'RSS 订阅' })

    fireEvent.click(
      within(screen.getByRole('region', { name: 'RSS 订阅' })).getByRole(
        'button',
        { name: '管理' },
      ),
    )
    expect(useReaderUi.getState().section).toBe('subscriptions')

    fireEvent.click(
      within(screen.getByRole('region', { name: '收件箱' })).getByRole(
        'button',
        { name: '管理' },
      ),
    )
    expect(useReaderUi.getState().section).toBe('inbox')

    fireEvent.click(
      within(screen.getByRole('region', { name: 'Obsidian' })).getByRole(
        'button',
        { name: '管理' },
      ),
    )
    expect(useReaderUi.getState().section).toBe('obsidian')
  })

  it('api_source / newsletter → 打开设置并直达对应分类', async () => {
    mocks.listSources.mockResolvedValue(SOURCE_OK)
    const opened: Array<string | undefined> = []
    const off = onOpenSettingsRequest((detail) => opened.push(detail.category))
    render(withProviders(<SourcesPage />))
    await screen.findByRole('region', { name: 'API 来源' })

    fireEvent.click(
      within(screen.getByRole('region', { name: 'API 来源' })).getByRole(
        'button',
        { name: '管理' },
      ),
    )
    fireEvent.click(
      within(screen.getByRole('region', { name: '邮件桥' })).getByRole(
        'button',
        { name: '管理' },
      ),
    )
    expect(opened).toContain('api-sources')
    expect(opened).toContain('mail')
    off()
  })

  it('rsshub → 添加来源对话框直达 RSSHub 模式（RssHubTab 路由目录）', async () => {
    mocks.listSources.mockResolvedValue(SOURCE_OK)
    mocks.getRssHubRoutes.mockResolvedValue({
      configured: true,
      routes: [
        { id: 'bilibili/user', title: 'B站UP主', description: '投稿', parameters: [] },
      ],
    })
    render(withProviders(<SourcesPage />))
    await screen.findByRole('region', { name: 'RSSHub 路由' })

    fireEvent.click(
      within(screen.getByRole('region', { name: 'RSSHub 路由' })).getByRole(
        'button',
        { name: '管理' },
      ),
    )
    // Phase K：对话框懒加载 chunk——CI 慢机放宽超时（同 gate1 约定）
    const dialog = await screen.findByRole(
      'dialog',
      { name: '添加来源' },
      { timeout: 8000 },
    )
    // 初始模式即 RSSHub（非默认 RSS/Atom）
    expect(
      within(dialog)
        .getByRole('tab', { name: 'RSSHub' })
        .getAttribute('aria-selected'),
    ).toBe('true')
    // RssHubTab 面板真实挂载（路由目录搜索框）
    expect(
      await within(dialog).findByRole('searchbox', {
        name: '搜索 RSSHub 路由',
      }),
    ).toBeInTheDocument()
  })

  it('「添加来源」按钮 → 打开对话框（默认 RSS/Atom 模式）', async () => {
    mocks.listSources.mockResolvedValue(SOURCE_OK)
    render(withProviders(<SourcesPage />))
    await screen.findByRole('region', { name: 'RSS 订阅' })

    fireEvent.click(screen.getAllByRole('button', { name: /添加来源/ })[0]!)
    const dialog = await screen.findByRole(
      'dialog',
      { name: '添加来源' },
      { timeout: 8000 },
    )
    expect(
      within(dialog)
        .getByRole('tab', { name: 'RSS / Atom' })
        .getAttribute('aria-selected'),
    ).toBe('true')
  })
})

describe('P04 导航入口', () => {
  it('MobileTabBar「来源」tab（替换原「订阅」）→ sources section', () => {
    render(<MobileTabBar />)
    const nav = screen.getByRole('navigation', { name: '底部导航' })
    const labels = [...nav.querySelectorAll('button')].map((b) =>
      b.textContent?.trim(),
    )
    expect(labels).toEqual(['首页', '来源', '搜索', '收藏'])
    fireEvent.click(within(nav).getByRole('button', { name: '来源' }))
    expect(useReaderUi.getState().section).toBe('sources')
  })

  it('桌面侧栏含「来源」入口 → sources section；RSS 订阅行保留', () => {
    render(withProviders(<Sidebar />))
    const nav = screen.getByRole('navigation', { name: '主导航' })
    expect(within(nav).getByRole('button', { name: /RSS 订阅/ })).toBeInTheDocument()
    fireEvent.click(within(nav).getByRole('button', { name: '来源' }))
    expect(useReaderUi.getState().section).toBe('sources')
  })
})
