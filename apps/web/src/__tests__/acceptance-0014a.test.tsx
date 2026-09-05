/** 0014a 测试 — UI Acceptance & Navigation Consistency。
 *
 * Gate 1：桌面 Sidebar「添加来源」入口 ↔ 复用 AddSourceDialog；
 *        订阅管理页保留 添加来源 / 导入 OPML / 导出 OPML。
 * Gate 2：移动端 收藏 → 全屏 Reader 布局契约（section 让位 max-lg:hidden，
 *        back 返回原列表，section/view/scope 不变）。
 * Gate 3：设置「账户与服务」不再出现 stale planned·0013；运营项指向 0018。
 *
 * 本文件只断言 interaction / DOM semantics；真实视觉效果归 0014a
 * Gate 4 Playwright 验收（桌面 1440×900 / 移动 390×844）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import Sidebar from '../components/Sidebar'
import SettingsModal from '../components/settings/SettingsModal'
import type { EntryListResponse } from '../api/types'
import { useReaderUi } from '../store/reader-ui'

const FEEDS = [
  { title: '示例源 A', feedUrl: 'https://a.example.com/feed.xml', category: null },
]

const SUBSCRIPTIONS = [
  {
    subscriptionRef: 's1.ZmVlZC8x',
    title: '示例源 A',
    feedUrl: 'https://a.example.com/feed.xml',
    category: null,
  },
]

const CATEGORIES = [{ id: 'user/-/label/技术', label: '技术' }]

function entry(ref: string): EntryListResponse['items'][number] {
  return {
    entryRef: ref,
    title: `文章 ${ref}`,
    feedTitle: '示例源 A',
    author: null,
    url: null,
    publishedAt: '2026-08-28T00:00:00Z',
    read: false,
    starred: true,
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

/** Sidebar-only（桌面上下文）：feeds + 入口；RssHub 路由等按需 mock。 */
function sidebarFetchMock() {
  return vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.startsWith('/api/v1/feeds')) return jsonResponse(FEEDS)
    throw new Error(`unexpected fetch: ${url}`)
  })
}

function withProviders(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

beforeEach(() => {
  localStorage.clear()
  useReaderUi.setState({
    section: 'home',
    view: 'all',
    scope: { kind: 'all' },
    selectedEntryRef: null,
    mobileSidebarOpen: false,
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

// ---------------------------------------------------------------------------
// Gate 1 — Desktop 添加来源可发现性
// ---------------------------------------------------------------------------

describe('0014a Gate 1 — Desktop Add Source', () => {
  it('桌面 Sidebar 显示「添加来源」入口（button + aria-label + title）', () => {
    vi.stubGlobal('fetch', sidebarFetchMock())
    render(withProviders(<Sidebar />))
    const add = screen.getByRole('button', { name: '添加来源' })
    expect(add).toBeEnabled()
    expect(add.tagName).toBe('BUTTON')
    expect(add).toHaveAttribute('title', '添加来源')
  })

  it('点击 → 打开与订阅管理页同一个 AddSourceDialog（三模式 tab，单一对话框）', async () => {
    vi.stubGlobal('fetch', sidebarFetchMock())
    render(withProviders(<Sidebar />))
    fireEvent.click(screen.getByRole('button', { name: '添加来源' }))

    const dialog = await screen.findByRole('dialog', { name: '添加来源' })
    expect(dialog).toBeInTheDocument()
    // 三种来源模式均可见；默认落在直接 RSS/Atom
    expect(screen.queryAllByRole('dialog')).toHaveLength(1)
    expect(screen.getByRole('tab', { name: 'RSS / Atom' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: '网站' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'RSSHub' })).toBeInTheDocument()
    expect(screen.getByLabelText('RSS / Atom 地址')).toBeInTheDocument()
  })

  it('关闭重开：Escape 关闭对话框（Dialog primitive 生效）', async () => {
    vi.stubGlobal('fetch', sidebarFetchMock())
    render(withProviders(<Sidebar />))
    fireEvent.click(screen.getByRole('button', { name: '添加来源' }))
    await screen.findByRole('dialog', { name: '添加来源' })
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    // 重开后重置为 RSS/Atom tab
    fireEvent.click(screen.getByRole('button', { name: '添加来源' }))
    await screen.findByRole('dialog', { name: '添加来源' })
    expect(screen.getByRole('tab', { name: 'RSS / Atom' })).toHaveAttribute('aria-selected', 'true')
  })

  it('移动抽屉上下文（onNavigate 提供）不渲染桌面入口与对话框', () => {
    vi.stubGlobal('fetch', sidebarFetchMock())
    render(withProviders(<Sidebar onNavigate={() => {}} />))
    expect(screen.queryByRole('button', { name: '添加来源' })).toBeNull()
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('桌面 App：Sidebar 入口打开唯一对话框；订阅管理页管理动作（添加来源/导入/导出 OPML）保留', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.startsWith('/api/v1/feeds')) return jsonResponse(FEEDS)
        if (url === '/api/v1/subscriptions') return jsonResponse(SUBSCRIPTIONS)
        if (url === '/api/v1/categories') return jsonResponse(CATEGORIES)
        if (url.startsWith('/api/v1/entries')) {
          return jsonResponse({ items: [entry('e1.a')], nextCursor: null })
        }
        throw new Error(`unexpected fetch: ${url}`)
      }),
    )
    useReaderUi.setState({ section: 'subscriptions' })
    render(withProviders(<App />))

    // 订阅管理页动作齐全（0014a：新增 导出 OPML）
    const controls = await screen.findByRole('group', { name: '订阅管理动作' })
    expect(within(controls).getByRole('button', { name: /添加来源/ })).toBeEnabled()
    expect(within(controls).getByRole('button', { name: /导入 OPML/ })).toBeEnabled()
    expect(within(controls).getByRole('button', { name: /导出 OPML/ })).toBeEnabled()

    // 桌面 Sidebar 添加来源 → 对话框；整个 DOM 只有一个 dialog
    const sidebarAside = document.querySelector('aside')!
    fireEvent.click(within(sidebarAside as HTMLElement).getByRole('button', { name: '添加来源' }))
    await screen.findByRole('dialog', { name: '添加来源' })
    expect(screen.queryAllByRole('dialog')).toHaveLength(1)

    // 订阅管理页自身的 AddSourceDialog 实例未同时打开
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })
})

// ---------------------------------------------------------------------------
// Gate 2 — 移动端 收藏 → 全屏 Reader
// ---------------------------------------------------------------------------

describe('0014a Gate 2 — Mobile favorites → full-screen Reader', () => {
  function mockFavoritesApi() {
    return vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('/api/v1/feeds')) return jsonResponse(FEEDS)
      if (url.includes('view=starred')) {
        return jsonResponse({ items: [entry('e1.fav')], nextCursor: null })
      }
      if (url.startsWith('/api/v1/entries/e1.fav')) {
        return jsonResponse({
          entryRef: 'e1.fav',
          title: '文章 e1.fav',
          feedTitle: '示例源 A',
          author: null,
          url: 'https://example.com/article',
          publishedAt: null,
          read: false,
          starred: true,
          contentText: '纯文本正文',
          contentHtml: '<p>收藏正文</p>',
        })
      }
      if (url.startsWith('/api/v1/entries')) {
        return jsonResponse({ items: [entry('e1.fav')], nextCursor: null })
      }
      throw new Error(`unexpected fetch: ${url}`)
    })
  }

  it('收藏 → 点文章 → section 让位（max-lg:hidden）→ Reader 占用版面；back 返回收藏（section/view/scope 不变）', async () => {
    vi.stubGlobal('fetch', mockFavoritesApi())
    useReaderUi.setState({ section: 'favorites', view: 'starred', scope: { kind: 'all' } })
    render(withProviders(<App />))

    // 收藏列表可见
    const favoritesSection = await screen.findByRole('region', { name: '收藏' })
    expect(favoritesSection).toHaveClass('lg:hidden')
    expect(favoritesSection).not.toHaveClass('max-lg:hidden')

    // 打开文章（收藏卡片标题按钮，取第一个实例——时间线与收藏页双渲染）
    fireEvent.click((await within(favoritesSection).findAllByRole('button', { name: /文章 e1\.fav/ }))[0]!)
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.fav')

    // 移动端 section 页面让位 → Reader 全屏；桌面忽略（section 本就 lg:hidden）
    await waitFor(() => expect(favoritesSection).toHaveClass('max-lg:hidden'))

    // Reader 可见（未 hidden）
    await screen.findByText('收藏正文')
    const main = document.querySelector('main')!
    const readerSection = Array.from(main.querySelectorAll(':scope > section')).find((s) =>
      s.textContent?.includes('收藏正文'),
    ) as HTMLElement
    expect(readerSection).toBeDefined()
    expect(readerSection).not.toHaveClass('hidden')

    // 收藏状态与来源不变（没有跳到别的 source/section）
    expect(useReaderUi.getState().section).toBe('favorites')
    expect(useReaderUi.getState().view).toBe('starred')

    // back → 返回收藏列表，section/view/scope 保持
    fireEvent.click(screen.getByRole('button', { name: '返回文章列表' }))
    expect(useReaderUi.getState().selectedEntryRef).toBeNull()
    expect(useReaderUi.getState().section).toBe('favorites')
    expect(useReaderUi.getState().view).toBe('starred')
    await waitFor(() => expect(favoritesSection).not.toHaveClass('max-lg:hidden'))
    expect(await within(favoritesSection).findByText('文章 e1.fav')).toBeInTheDocument()
  })

  it('首页时间线（另一列表）→ 文章 → back 仍一致（既有契约回归）', async () => {
    vi.stubGlobal('fetch', mockFavoritesApi())
    render(withProviders(<App />))
    fireEvent.click((await screen.findAllByRole('button', { name: /文章 e1\.fav/ }))[0]!)
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.fav')
    const listSection = Array.from(
      document.querySelector('main')!.querySelectorAll(':scope > section'),
    )[0] as HTMLElement
    expect(listSection).toHaveClass('hidden')
    fireEvent.click(screen.getByRole('button', { name: '返回文章列表' }))
    expect(useReaderUi.getState().section).toBe('home')
    expect(listSection).not.toHaveClass('hidden')
  })
})

// ---------------------------------------------------------------------------
// Gate 3 — FreshRSS / RSSHub 设置真实性
// ---------------------------------------------------------------------------

describe('0014a Gate 3 — Service settings truthfulness', () => {
  function renderSettings() {
    render(withProviders(<SettingsModal open onClose={vi.fn()} />))
  }

  const OPERATIONS_STATUS = {
    lumi: { status: 'healthy', version: '0.1.0' },
    sqlite: { status: 'healthy' },
    freshrss: { status: 'unavailable', configured: true, latencyMs: null, lastCheckedAt: null, error: { type: 'http_error' } },
    rsshub: { status: 'healthy', configured: true, latencyMs: 42, lastCheckedAt: null, error: null, restartRequired: true, pendingConfigCount: 2 },
    backup: { webdavConfigured: false, lastBackup: null },
  }

  function stubSettingsFetch() {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = String(input)
        if (url === '/api/v1/operations/status') return jsonResponse(OPERATIONS_STATUS)
        if (url === '/api/v1/backups') return jsonResponse([])
        if (url === '/api/v1/backups/webdav') {
          return jsonResponse({ configured: false, serverUrl: '', username: '', remoteDir: '', tlsVerify: true, passwordConfigured: false })
        }
        throw new Error(`unexpected fetch: ${url}`)
      }),
    )
  }

  it('账户与服务（0018 G9）：渲染真实依赖状态行（非 planned 占位）', async () => {
    stubSettingsFetch()
    renderSettings()
    fireEvent.click(screen.getByRole('button', { name: /账户与服务/ }))
    // 真实 Operations UI：Lumi/FreshRSS/RSSHub/备份 四行 + 探测结果
    expect(await screen.findByText('LumiRSS')).toBeInTheDocument()
    // 侧栏分类按钮也叫 RSSHub，取行内所有实例断言
    expect(screen.getAllByText('FreshRSS').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('RSSHub').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('连接失败')).toBeInTheDocument()
    expect(screen.getByText('延迟 42 ms')).toBeInTheDocument()
    expect(screen.getByText('2 项待生效')).toBeInTheDocument()
    // stale 占位彻底移除
    expect(screen.queryByText('FreshRSS 维护操作')).not.toBeInTheDocument()
    expect(screen.queryByText('RSSHub 运营中心')).not.toBeInTheDocument()
    expect(screen.queryByText(/planned · 0013/)).toBeNull()
    expect(screen.queryByText(/planned · 0018/)).toBeNull()
    vi.unstubAllGlobals()
  })

  it('数据控制包含真实备份 UI；独立「备份与恢复」分类已并入', () => {
    stubSettingsFetch()
    renderSettings()
    fireEvent.click(screen.getByRole('button', { name: /数据控制/ }))
    expect(screen.getByText('备份概览')).toBeInTheDocument()
    expect(screen.getByText('备份历史')).toBeInTheDocument()
    expect(screen.getByText('WebDAV 远程备份')).toBeInTheDocument()
    expect(screen.getByText('配置迁移（本设备 UI 设置）')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /备份与恢复/ })).toBeNull()
    expect(screen.queryByText(/planned · 0013/)).toBeNull()
    expect(screen.queryByText('已实现 · 0013')).not.toBeInTheDocument()
    vi.unstubAllGlobals()
  })

  it('通用：未实现的侧栏隐藏已读已整体移除（不向用户暴露 planned）', () => {
    renderSettings()
    expect(screen.queryByText('侧栏隐藏已读')).toBeNull()
    expect(screen.queryByText(/planned · 0013/)).toBeNull()
    expect(screen.queryByText('planned', { exact: true })).toBeNull()
  })
})
