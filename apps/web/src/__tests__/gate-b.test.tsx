/** Gate B 测试 — 快捷键 + 分类页真实/planned 语义（AC5–AC10）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import SettingsModal from '../components/settings/SettingsModal'
import { useAppSettings } from '../store/app-settings'
import { useReaderUi } from '../store/reader-ui'
import { SHORTCUTS, useKeyboardShortcuts } from '../lib/keyboard-shortcuts'

/** 挂载快捷键 hook 的宿主组件（模拟 App 行为） */
function ShortcutHost() {
  useKeyboardShortcuts()
  return null
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const OPERATIONS_STATUS_OK = {
  lumi: { status: 'healthy', version: '0.1.0' },
  sqlite: { status: 'healthy' },
  freshrss: { status: 'unconfigured', configured: false, latencyMs: null, lastCheckedAt: null, error: null },
  rsshub: { status: 'unconfigured', configured: false, latencyMs: null, lastCheckedAt: null, error: null, restartRequired: false, pendingConfigCount: 0 },
  backup: { webdavConfigured: false, lastBackup: null },
}

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  // 预置缓存：2 条文章（供 j/k 导航与 s 收藏取数）
  queryClient.setQueryData(['feeds'], [
    { title: '源A', feedUrl: 'https://a.example/feed', category: null },
  ])
  queryClient.setQueryData(['entries', { view: 'all', scope: 'all' }], {
    pages: [
      {
        items: [
          { entryRef: 'e1.a', title: 'A', starred: false },
          { entryRef: 'e1.b', title: 'B', starred: true },
        ],
      },
    ],
  })
  return <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
}

describe('快捷键速查表页（AC7）', () => {
  it('渲染全部基础快捷键（与 SHORTCUTS 同源）', async () => {
    render(renderWithProviders(<SettingsModal open onClose={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /快捷键/ }))
    await waitFor(() => {
      for (const s of SHORTCUTS) {
        expect(screen.getByText(s.action)).toBeInTheDocument()
      }
    })
  })
})

describe('快捷键行为（j/k/u/s）', () => {
  function resetState() {
    useReaderUi.setState({ view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
    localStorage.clear()
  }

  it('j：无选中 → 选中第一篇', () => {
    resetState()
    render(renderWithProviders(<ShortcutHost />))
    fireEvent.keyDown(window, { key: 'j' })
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.a')
  })

  it('j 再按：选中第二篇；k 回到第一篇', () => {
    resetState()
    render(renderWithProviders(<ShortcutHost />))
    fireEvent.keyDown(window, { key: 'j' })
    fireEvent.keyDown(window, { key: 'j' })
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.b')
    fireEvent.keyDown(window, { key: 'k' })
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.a')
  })

  it('u：all ↔ unread 切换', () => {
    resetState()
    render(renderWithProviders(<ShortcutHost />))
    fireEvent.keyDown(window, { key: 'u' })
    expect(useReaderUi.getState().view).toBe('unread')
    fireEvent.keyDown(window, { key: 'u' })
    expect(useReaderUi.getState().view).toBe('all')
  })

  it('s：选中文章发起收藏 mutation（PATCH starred）', async () => {
    resetState()
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(null, { status: 204 }),
    )
    vi.stubGlobal('fetch', fetchMock)
    render(renderWithProviders(<ShortcutHost />))
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    fireEvent.keyDown(window, { key: 's' })
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1)
      const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
      expect(JSON.parse(String(init.body))).toEqual({ starred: true })
    })
    vi.unstubAllGlobals()
  })

  it('输入框聚焦时不劫持（硬边界 10）', () => {
    resetState()
    render(
      renderWithProviders(
        <>
          <ShortcutHost />
          <input aria-label="测试输入" data-testid="input" />
        </>,
      ),
    )
    const input = screen.getByTestId('input')
    input.focus()
    // 在 input 上按 j（事件 target=input，冒泡到 window 的监听器）
    fireEvent.keyDown(input, { key: 'j' })
    expect(useReaderUi.getState().selectedEntryRef).toBeNull()
  })
})

describe('分类页 planned 语义（AC10）', () => {
  it('订阅与来源页：OPML 导入/导出真实可用（0013 Gate 4）；来源发现指向订阅中心（0014）', async () => {
    // SourcesSettingsSection 会真实请求 subscriptions / freshrss-ui
    const routes: Record<string, () => Response> = {
      'GET /api/v1/subscriptions': () => jsonResponse([]),
      'GET /api/v1/freshrss-ui': () => jsonResponse({ url: null }),
      'GET /api/v1/operations/status': () => jsonResponse(OPERATIONS_STATUS_OK),
    }
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const handler = routes[`GET ${String(input)}`]
        if (handler === undefined) throw new Error(`unexpected fetch: ${String(input)}`)
        return handler()
      }),
    )
    render(renderWithProviders(<SettingsModal open onClose={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /订阅与来源/ }))
    // 0013 Gate 4：OPML 导出为真实可点按钮；导入文件选择器存在（不再 planned 禁用）
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '导出 OPML' })).toBeEnabled()
    })
    expect(screen.getByLabelText(/选择 OPML 文件/)).toBeInTheDocument()
    vi.unstubAllGlobals()
  })

  it('AI 页：用途分配 / Profile / 默认配置真实可用（浏览器可管理 Key）', async () => {
    const AI_SETTINGS = {
      provider: 'openai_compatible',
      baseUrl: '',
      model: '',
      summaryLanguage: 'zh-CN',
      translationLanguage: 'zh-CN',
      configured: false,
      envKeyConfigured: false,
      defaultKeyConfigured: false,
      purposes: { summary: 'default', translation: 'default', chat: 'default' },
      purposeStatus: {
        summary: { profileId: 'default', source: 'default', profileLabel: null, baseUrl: '', model: '', keyConfigured: false, keySource: 'missing', configured: false },
        translation: { profileId: 'default', source: 'default', profileLabel: null, baseUrl: '', model: '', keyConfigured: false, keySource: 'missing', configured: false },
        chat: { profileId: 'default', source: 'default', profileLabel: null, baseUrl: '', model: '', keyConfigured: false, keySource: 'missing', configured: false },
      },
    }
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        if (String(input) === '/api/v1/settings/ai') {
          return Promise.resolve(jsonResponse(AI_SETTINGS))
        }
        if (String(input) === '/api/v1/settings/ai/profiles') {
          return Promise.resolve(jsonResponse([]))
        }
        throw new Error(`unexpected fetch: ${String(input)}`)
      }),
    )
    render(renderWithProviders(<SettingsModal open onClose={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /^AI$/ }))
    await waitFor(() => {
      expect(screen.getByText('用途分配')).toBeInTheDocument()
      expect(screen.getByLabelText('摘要使用的配置')).toBeInTheDocument()
      expect(screen.getByLabelText('翻译使用的配置')).toBeInTheDocument()
      expect(screen.getByLabelText('AI 对话使用的配置')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /新建 Profile/ })).toBeInTheDocument()
      expect(screen.getByText('默认 API Key')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: '设置 Key' })).toBeInTheDocument()
      expect(screen.getByLabelText('默认 Base URL')).toBeInTheDocument()
      expect(screen.getByLabelText('默认 Model')).toBeInTheDocument()
      expect(screen.getByLabelText('摘要语言')).toBeInTheDocument()
      expect(screen.getByLabelText('翻译语言')).toBeInTheDocument()
    })
    vi.unstubAllGlobals()
  })

  it('数据控制页：缓存/设置/配置迁移/完整备份同页管理；独立「备份与恢复」分类已并入', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = String(input)
        if (url === '/api/v1/backups') return Promise.resolve(jsonResponse([]))
        if (url === '/api/v1/operations/status') return Promise.resolve(jsonResponse(OPERATIONS_STATUS_OK))
        if (url === '/api/v1/backups/webdav') {
          return Promise.resolve(jsonResponse({ configured: false, serverUrl: '', username: '', remoteDir: '', tlsVerify: true, passwordConfigured: false }))
        }
        throw new Error(`unexpected fetch: ${url}`)
      }),
    )
    render(renderWithProviders(<SettingsModal open onClose={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /数据控制/ }))
    await waitFor(() => {
      expect(screen.getByText(/清除本地缓存/)).toBeInTheDocument()
      expect(screen.getByText(/恢复默认设置/)).toBeInTheDocument()
    })
    // 真实按钮可点
    expect(screen.getByRole('button', { name: '清除' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '重置' })).toBeEnabled()
    // 配置迁移 + 完整备份 + WebDAV 同页可访问
    expect(screen.getByText(/配置迁移（本设备 UI 设置）/)).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByText(/创建完整备份（本机）/)).toBeInTheDocument()
      expect(screen.getByText('WebDAV 远程备份')).toBeInTheDocument()
    })
    // 左侧导航不再有独立「备份与恢复」分类
    expect(screen.queryByRole('button', { name: /备份与恢复/ })).toBeNull()
    vi.unstubAllGlobals()
  })

  it('重置真实生效：改设置 → 点重置 → 恢复默认', async () => {
    localStorage.clear()
    useAppSettings.getState().update({ readerFontSize: 21 })
    expect(useAppSettings.getState().settings.readerFontSize).toBe(21)
    render(renderWithProviders(<SettingsModal open onClose={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /数据控制/ }))
    fireEvent.click(await screen.findByRole('button', { name: '重置' }))
    expect(useAppSettings.getState().settings.readerFontSize).toBe(17)
    localStorage.clear()
  })

  it('关于页：版本/许可证/仓库/第三方链接齐全（AC9）', async () => {
    render(renderWithProviders(<SettingsModal open onClose={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /关于/ }))
    await waitFor(() => {
      expect(screen.getByText(/AGPL-3\.0-only/)).toBeInTheDocument()
      expect(screen.getByText(/paidethon\/LumiRSS/)).toBeInTheDocument()
      expect(screen.getByText(/THIRD_PARTY_NOTICES/)).toBeInTheDocument()
    })
  })
})

describe('0020 AUDIT-013 — j/k 滚动定位到真实 data-entry-ref 元素', () => {
  it('j 选中项对应的 div[data-entry-ref] 被 scrollIntoView（而非不存在的 button 嵌套选择器）', async () => {
    useReaderUi.setState({ view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
    localStorage.clear()
    let scrolledRef: string | null = null
    const original = Element.prototype.scrollIntoView
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolledRef = this.getAttribute('data-entry-ref')
    } as never
    // rAF 同步执行，便于确定性断言
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      cb(0)
      return 0
    })
    render(
      renderWithProviders(
        <>
          <ShortcutHost />
          <div data-entry-ref="e1.a">A</div>
          <div data-entry-ref="e1.b">B</div>
        </>,
      ),
    )
    fireEvent.keyDown(window, { key: 'j' })
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.a')
    await waitFor(() => expect(scrolledRef).toBe('e1.a'))
    Element.prototype.scrollIntoView = original
    vi.unstubAllGlobals()
  })
})

describe('0020 AUDIT-014 — 模态打开时全局快捷键不改动隐藏的 Reader/timeline', () => {
  it('dialog + j：不改变选中项', () => {
    useReaderUi.setState({ view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
    localStorage.clear()
    render(
      renderWithProviders(
        <>
          <ShortcutHost />
          <div role="dialog" aria-modal="true">modal</div>
        </>,
      ),
    )
    fireEvent.keyDown(window, { key: 'j' })
    expect(useReaderUi.getState().selectedEntryRef).toBeNull()
  })

  it('dialog + s：不发起收藏 mutation', async () => {
    useReaderUi.setState({ view: 'all', scope: { kind: 'all' }, selectedEntryRef: 'e1.a' })
    localStorage.clear()
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)
    render(
      renderWithProviders(
        <>
          <ShortcutHost />
          <div role="dialog" aria-modal="true">modal</div>
        </>,
      ),
    )
    fireEvent.keyDown(window, { key: 's' })
    await new Promise((r) => setTimeout(r, 20))
    expect(fetchMock).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it('dialog + u：不切换未读视图', () => {
    useReaderUi.setState({ view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
    localStorage.clear()
    render(
      renderWithProviders(
        <>
          <ShortcutHost />
          <div role="dialog" aria-modal="true">modal</div>
        </>,
      ),
    )
    fireEvent.keyDown(window, { key: 'u' })
    expect(useReaderUi.getState().view).toBe('all')
  })

  it('无模态时 j 照常工作（守卫不误伤）', () => {
    useReaderUi.setState({ view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
    localStorage.clear()
    render(renderWithProviders(<ShortcutHost />))
    fireEvent.keyDown(window, { key: 'j' })
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.a')
  })
})

describe('未读圆点固定视觉语义（AC5）', () => {
  it('未读行渲染 accent 圆点；已读行为透明占位（对齐保留，状态不只靠颜色）', async () => {
    // 直接驱动 store + 渲染 EntryRow
    const { default: EntryRow } = await import('../components/EntryRow')
    const unread = {
      entryRef: 'e1.x', title: '标题', feedTitle: '源', author: null,
      url: null, publishedAt: null, read: false, starred: false,
    }
    const read = { ...unread, read: true }
    localStorage.clear()
    // EntryRow 内嵌 EntryActionButtons（mutation hook），需要 QueryClientProvider
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container, unmount } = render(
      <QueryClientProvider client={qc}>
        <>
          <EntryRow item={unread} selected={false} />
          <EntryRow item={read} selected={false} />
        </>
      </QueryClientProvider>,
    )
    const dots = container.querySelectorAll('span.rounded-full')
    expect(dots.length).toBe(2)
    expect(dots[0].className).toContain('bg-[var(--lumi-accent)]')
    expect(dots[1].className).toContain('bg-transparent')
    unmount()
    localStorage.clear()
  })
})
