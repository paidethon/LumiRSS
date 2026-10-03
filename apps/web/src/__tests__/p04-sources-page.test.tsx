/** R02 — 统一内容来源管理中心（SourcesPage）+ 底栏/侧栏「来源」入口。
 *
 * 统一 vi.mock('../api/client')（保留其余真实导出）：mock
 * listSourcesSummary（GET /api/v1/sources/summary 按类型汇总——字段只有
 * type/count/status/lastActivityAt/detail，断言不发明状态）与
 * getRssHubRoutes（添加来源 RSSHub 深链的路由目录）。覆盖：
 * - 九类来源与 nav-registry sourceTypeSourceOrder 同序渲染；
 * - 真实数量 / 状态（已连接·正常·暂无内容·未配置·最近错误）/ 最近更新；
 * - 「服务未配置」与「集合为空」严格区分（首启空态 = EmptyState +
 *   单一主 CTA）；
 * - 每类主操作深链：rss→订阅中心、inbox/obsidian/bookmark/clip/snapshot
 *   →对应 section、api_source/newsletter→设置直达分类、rsshub→添加来源
 *   RssHubTab；
 * - 搜索 / 类型 / 状态过滤（Toolbar + ActionMenu）与清除过滤空态；
 * - 加载 / 错误重试状态；
 * - MobileTabBar「来源」tab；桌面侧栏「来源」入口。
 */

import { fireEvent, render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SourcesPage from '../components/pages/SourcesPage'
import MobileTabBar from '../components/MobileTabBar'
import Sidebar from '../components/Sidebar'
import { useReaderUi } from '../store/reader-ui'
import { onOpenSettingsRequest } from '../components/settings/settings-bridge'
import { sourceTypeSourceOrder } from '../lib/nav-registry'
import type { SourcesSummaryResponse } from '../api/client'

const mocks = vi.hoisted(() => ({
  listSourcesSummary: vi.fn<() => Promise<SourcesSummaryResponse>>(),
  getRssHubRoutes: vi.fn<() => Promise<{ configured: boolean; routes: Array<{ id: string; title: string; description: string; parameters: never[] }> }>>(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    listSourcesSummary: mocks.listSourcesSummary,
    getRssHubRoutes: mocks.getRssHubRoutes,
  }
})

function withProviders(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

/** 与 services/bff sources.py summary 的投影形状逐字段一致（不发明字段）：
 * 九类齐 + 四种状态都有代表。 */
const SUMMARY_MIXED: SourcesSummaryResponse = {
  generatedAt: '2026-10-01T00:00:00Z',
  items: [
    { type: 'rss', count: 12, status: 'ok', lastActivityAt: '2026-09-30T08:00:00Z', detail: null },
    { type: 'rsshub', count: 3, status: 'ok', lastActivityAt: null, detail: null },
    { type: 'api_source', count: 1, status: 'error', lastActivityAt: null, detail: '上游超时' },
    { type: 'newsletter', count: null, status: 'not_configured', lastActivityAt: null, detail: null },
    { type: 'inbox', count: 5, status: 'ok', lastActivityAt: '2026-09-29T10:00:00Z', detail: null },
    { type: 'obsidian', count: null, status: 'not_configured', lastActivityAt: null, detail: null },
    { type: 'bookmark', count: 8, status: 'ok', lastActivityAt: '2026-09-28T00:00:00Z', detail: null },
    { type: 'clip', count: 0, status: 'empty', lastActivityAt: null, detail: null },
    { type: 'snapshot', count: 2, status: 'ok', lastActivityAt: '2026-09-27T00:00:00Z', detail: null },
  ],
}

/** 首启：九类全部 not_configured / empty。 */
const SUMMARY_FRESH: SourcesSummaryResponse = {
  generatedAt: '2026-10-01T00:00:00Z',
  items: [
    { type: 'rss', count: 0, status: 'not_configured', lastActivityAt: null, detail: null },
    { type: 'rsshub', count: null, status: 'not_configured', lastActivityAt: null, detail: null },
    { type: 'api_source', count: 0, status: 'not_configured', lastActivityAt: null, detail: null },
    { type: 'newsletter', count: null, status: 'not_configured', lastActivityAt: null, detail: null },
    { type: 'inbox', count: 0, status: 'not_configured', lastActivityAt: null, detail: null },
    { type: 'obsidian', count: null, status: 'not_configured', lastActivityAt: null, detail: null },
    { type: 'bookmark', count: 0, status: 'empty', lastActivityAt: null, detail: null },
    { type: 'clip', count: 0, status: 'empty', lastActivityAt: null, detail: null },
    { type: 'snapshot', count: 0, status: 'empty', lastActivityAt: null, detail: null },
  ],
}

function rowOf(label: string): HTMLElement {
  // 过滤菜单触发按钮可能同文（如选中「收件箱」后的触发器）——只在
  // 列表行（li）内匹配。
  for (const el of screen.getAllByText(label)) {
    const row = el.closest('li')
    if (row instanceof HTMLElement) return row
  }
  throw new Error(`row not found: ${label}`)
}

beforeEach(() => {
  useReaderUi.setState({
    section: 'home',
    scope: { kind: 'all' },
    view: 'all',
    selectedEntryRef: null,
    mobileSidebarOpen: false,
  })
  mocks.listSourcesSummary.mockReset()
  mocks.getRssHubRoutes.mockReset()
})

describe('SourcesPage 九类渲染（R02 AC）', () => {
  it('九类与 nav-registry sourceTypeSourceOrder 同序，计数/状态/最近更新来自 summary', async () => {
    mocks.listSourcesSummary.mockResolvedValue(SUMMARY_MIXED)
    render(withProviders(<SourcesPage />))

    await screen.findByText('RSS 订阅')
    const rows = screen.getAllByRole('listitem')
    const labels = [
      'RSS 订阅',
      'RSSHub 路由',
      'API 来源',
      '邮件桥',
      '收件箱',
      'Obsidian',
      '书签',
      '网页剪藏',
      '网页快照',
    ]
    expect(labels).toEqual(sourceTypeSourceOrder().map((meta) => meta.label))
    expect(rows).toHaveLength(9)
    rows.forEach((row, i) => {
      expect(within(row).getByText(labels[i]!)).toBeInTheDocument()
    })

    // 真实数量（summary.count，绝不发明）
    expect(within(rowOf('RSS 订阅')).getByText('12 项')).toBeInTheDocument()
    expect(within(rowOf('网页剪藏')).getByText('0 项')).toBeInTheDocument()
    // 连接状态型（newsletter/obsidian）count=null → 不渲染伪计数
    expect(within(rowOf('邮件桥')).queryByText(/项/)).toBeNull()
    // 最近更新（格式化自 API 字段）
    expect(within(rowOf('RSS 订阅')).getByText(/最近更新：/)).toBeInTheDocument()
  })

  it('状态面诚实渲染：已连接/正常/暂无内容/未配置/最近错误 + detail 走 alert', async () => {
    mocks.listSourcesSummary.mockResolvedValue(SUMMARY_MIXED)
    render(withProviders(<SourcesPage />))
    await screen.findByText('RSS 订阅')

    // 服务类 ok → 已连接；集合类 ok → 正常
    expect(within(rowOf('RSS 订阅')).getByText('已连接')).toBeInTheDocument()
    expect(within(rowOf('书签')).getByText('正常')).toBeInTheDocument()
    // 集合为空 ≠ 服务未配置（两个状态、两种文案）
    expect(within(rowOf('网页剪藏')).getByText('暂无内容')).toBeInTheDocument()
    expect(within(rowOf('邮件桥')).getByText('未配置')).toBeInTheDocument()
    expect(within(rowOf('Obsidian')).getByText('未配置')).toBeInTheDocument()
    // error → 最近错误 + detail（role=alert）
    expect(within(rowOf('API 来源')).getByText('最近错误')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('上游超时')
  })

  it('首启（九类全部未配置/为空）→ EmptyState + 仅一个主要下一步', async () => {
    mocks.listSourcesSummary.mockResolvedValue(SUMMARY_FRESH)
    render(withProviders(<SourcesPage />))
    expect(await screen.findByText('还没有内容来源')).toBeInTheDocument()
    // 行列表不渲染（每类状态已由空态承载）
    expect(screen.queryByRole('listitem')).toBeNull()
    // 空态块内只有唯一的主要下一步（页头的「添加来源」是常驻工具位，
    // 不计入空态块）
    const emptyBlock = screen.getByText('还没有内容来源').closest('div')
    expect(emptyBlock).not.toBeNull()
    const emptyActions = within(emptyBlock as HTMLElement).getAllByRole('button', {
      name: /添加来源/,
    })
    expect(emptyActions).toHaveLength(1)
  })

  it('加载失败 → 错误态 + 重试成功后渲染九类', async () => {
    mocks.listSourcesSummary.mockRejectedValueOnce(new Error('BFF 不可达'))
    render(withProviders(<SourcesPage />))
    expect(await screen.findByText('来源汇总加载失败')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('BFF 不可达')

    mocks.listSourcesSummary.mockResolvedValue(SUMMARY_MIXED)
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByText('RSS 订阅')).toBeInTheDocument()
    expect(screen.getAllByRole('listitem')).toHaveLength(9)
  })
})

describe('SourcesPage 过滤（Toolbar + ActionMenu）', () => {
  it('搜索过滤 + 清除过滤空态', async () => {
    mocks.listSourcesSummary.mockResolvedValue(SUMMARY_MIXED)
    render(withProviders(<SourcesPage />))
    await screen.findByText('RSS 订阅')

    fireEvent.change(screen.getByRole('searchbox', { name: '搜索来源类型' }), {
      target: { value: '书签' },
    })
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
    expect(within(rowOf('书签')).getByText('8 项')).toBeInTheDocument()

    fireEvent.change(screen.getByRole('searchbox', { name: '搜索来源类型' }), {
      target: { value: '不存在的类型' },
    })
    expect(screen.getByText('没有匹配的来源')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '清除过滤' }))
    expect(screen.getAllByRole('listitem')).toHaveLength(9)
  })

  it('类型过滤：ActionMenu 选择后只留该类', async () => {
    mocks.listSourcesSummary.mockResolvedValue(SUMMARY_MIXED)
    render(withProviders(<SourcesPage />))
    await screen.findByText('RSS 订阅')

    fireEvent.click(screen.getByRole('button', { name: '全部类型' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '收件箱' }))
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
    expect(within(rowOf('收件箱')).getByText('5 项')).toBeInTheDocument()
  })

  it('状态过滤：未配置 → 只留未配置类', async () => {
    mocks.listSourcesSummary.mockResolvedValue(SUMMARY_MIXED)
    render(withProviders(<SourcesPage />))
    await screen.findByText('RSS 订阅')

    fireEvent.click(screen.getByRole('button', { name: '全部状态' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '未配置' }))
    const rows = screen.getAllByRole('listitem')
    expect(rows).toHaveLength(2)
    expect(within(rowOf('邮件桥')).getByText('未配置')).toBeInTheDocument()
    expect(within(rowOf('Obsidian')).getByText('未配置')).toBeInTheDocument()
  })
})

describe('SourcesPage 主操作深链（R02 AC）', () => {
  it('rss → 订阅中心；inbox / obsidian / bookmark / clip / snapshot → 对应 section', async () => {
    mocks.listSourcesSummary.mockResolvedValue(SUMMARY_MIXED)
    render(withProviders(<SourcesPage />))
    await screen.findByText('RSS 订阅')

    fireEvent.click(within(rowOf('RSS 订阅')).getByRole('button', { name: '订阅中心' }))
    expect(useReaderUi.getState().section).toBe('subscriptions')

    fireEvent.click(within(rowOf('收件箱')).getByRole('button', { name: '打开收件箱' }))
    expect(useReaderUi.getState().section).toBe('inbox')

    fireEvent.click(within(rowOf('Obsidian')).getByRole('button', { name: '打开 Obsidian' }))
    expect(useReaderUi.getState().section).toBe('obsidian')

    fireEvent.click(within(rowOf('书签')).getByRole('button', { name: '打开书签' }))
    expect(useReaderUi.getState().section).toBe('bookmarks')

    fireEvent.click(within(rowOf('网页剪藏')).getByRole('button', { name: '打开剪藏' }))
    expect(useReaderUi.getState().section).toBe('clips')

    fireEvent.click(within(rowOf('网页快照')).getByRole('button', { name: '打开快照' }))
    expect(useReaderUi.getState().section).toBe('snapshots')
  })

  it('api_source / newsletter → 打开设置并直达对应分类', async () => {
    mocks.listSourcesSummary.mockResolvedValue(SUMMARY_MIXED)
    const opened: Array<string | undefined> = []
    const off = onOpenSettingsRequest((detail) => opened.push(detail.category))
    render(withProviders(<SourcesPage />))
    await screen.findByText('RSS 订阅')

    fireEvent.click(within(rowOf('API 来源')).getByRole('button', { name: '管理' }))
    fireEvent.click(within(rowOf('邮件桥')).getByRole('button', { name: '管理连接' }))
    expect(opened).toContain('api-sources')
    expect(opened).toContain('mail')
    off()
  })

  it('rsshub → 添加来源对话框直达 RSSHub 模式（RssHubTab 路由目录）', async () => {
    mocks.listSourcesSummary.mockResolvedValue(SUMMARY_MIXED)
    mocks.getRssHubRoutes.mockResolvedValue({
      configured: true,
      routes: [
        { id: 'bilibili/user', title: 'B站UP主', description: '投稿', parameters: [] },
      ],
    })
    render(withProviders(<SourcesPage />))
    await screen.findByText('RSSHub 路由')

    fireEvent.click(
      within(rowOf('RSSHub 路由')).getByRole('button', { name: '添加路由' }),
    )
    // 对话框懒加载 chunk——CI 慢机放宽超时（同既有约定）
    const dialog = await screen.findByRole(
      'dialog',
      { name: '添加来源' },
      { timeout: 8000 },
    )
    expect(
      within(dialog)
        .getByRole('tab', { name: 'RSSHub' })
        .getAttribute('aria-selected'),
    ).toBe('true')
    expect(
      await within(dialog).findByRole('searchbox', {
        name: '搜索 RSSHub 路由',
      }),
    ).toBeInTheDocument()
  })

  it('「添加来源」按钮 → 打开对话框（默认 RSS/Atom 模式）', async () => {
    mocks.listSourcesSummary.mockResolvedValue(SUMMARY_MIXED)
    render(withProviders(<SourcesPage />))
    await screen.findByText('RSS 订阅')

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

describe('来源中心导航入口', () => {
  it('MobileTabBar「来源」tab → sources section', () => {
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
