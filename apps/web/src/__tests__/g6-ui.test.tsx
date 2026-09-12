/** phase2 G6 — Web UI 测试（API 来源 / 邮件简报 / Obsidian 库 / 统一搜索库分组 / 联合收藏）。
 *
 * - ApiSourcesSection：列表渲染（名称 / host / 正常徽标）；创建后一次性
 *   面板展示 atomPath + 复制按钮；
 * - MailSection：摘要设置 PUT 携带表单值（含 write-only 密码）；密码框
 *   永不回显（passwordConfigured=true 时 value 仍为空）；
 * - ObsidianPage：未配置 → 连接调用 PUT settings；已配置 → 列表渲染 +
 *   重扫报告行；
 * - SearchPage：data.library 存在时渲染「库」分组；libraryError 小字提示；
 * - FavoritesPage：RSS 收藏 + 库收藏两组渲染 + libraryError 提示。
 *
 * 统一 vi.mock('../api/client')（保留 ApiError 等真实导出）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type {
  ApiSource,
  DigestSettings,
  FavoritesResponse,
  MailBridgeListResponse,
  NoteListResponse,
  NoteView,
  ObsidianRescanResult,
  ObsidianStatus,
} from '../api/client'
import type { EntryListItem, SearchResponse } from '../api/types'
import { ApiError } from '../api/client'
import { ApiSourcesSection } from '../components/settings/ApiSourcesSection'
import { MailSection } from '../components/settings/MailSection'
import ObsidianPage from '../components/pages/ObsidianPage'
import SearchPage from '../components/pages/SearchPage'
import FavoritesPage from '../components/pages/FavoritesPage'
import { useReaderUi } from '../store/reader-ui'

const mocks = vi.hoisted(() => ({
  getFeeds: vi.fn(),
  searchEntries: vi.fn(),
  getEntries: vi.fn(),
  getFavorites: vi.fn(),
  listApiSources: vi.fn(),
  createApiSource: vi.fn(),
  listMailBridgeLists: vi.fn(),
  getDigestSettings: vi.fn(),
  updateDigestSettings: vi.fn(),
  sendDigestNow: vi.fn(),
  getObsidianStatus: vi.fn(),
  updateObsidianSettings: vi.fn(),
  listObsidianNotes: vi.fn(),
  rescanObsidian: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getFeeds: mocks.getFeeds,
    searchEntries: mocks.searchEntries,
    getEntries: mocks.getEntries,
    getFavorites: mocks.getFavorites,
    listApiSources: mocks.listApiSources,
    createApiSource: mocks.createApiSource,
    listMailBridgeLists: mocks.listMailBridgeLists,
    getDigestSettings: mocks.getDigestSettings,
    updateDigestSettings: mocks.updateDigestSettings,
    sendDigestNow: mocks.sendDigestNow,
    getObsidianStatus: mocks.getObsidianStatus,
    updateObsidianSettings: mocks.updateObsidianSettings,
    listObsidianNotes: mocks.listObsidianNotes,
    rescanObsidian: mocks.rescanObsidian,
  }
})

function withProviders(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

// ---- fixtures ----

function apiSourceFixture(over: Partial<ApiSource> = {}): ApiSource {
  return {
    uuid: 'src-1',
    name: 'Hacker News API',
    endpoint: 'https://hacker-news.firebaseio.com/v0/item.json',
    itemsExpr: 'items',
    fieldMap: { id: 'id', title: 'title', url: 'url', published: 'time', body: 'text' },
    enabled: true,
    createdAt: '2026-09-01T08:00:00Z',
    lastStatus: 'ok',
    lastError: null,
    lastSuccessAt: '2026-09-11T08:00:00Z',
    ...over,
  }
}

function digestSettingsFixture(over: Partial<DigestSettings> = {}): DigestSettings {
  return {
    enabled: true,
    hour: 8,
    source: 'read_later',
    limitCount: 10,
    smtpHost: 'smtp.example.com',
    smtpPort: 587,
    smtpUser: 'lumi',
    fromAddr: 'lumi@example.com',
    toAddr: 'me@example.com',
    lastSentAt: null,
    lastError: null,
    passwordConfigured: true,
    ...over,
  }
}

function obsidianStatusFixture(over: Partial<ObsidianStatus> = {}): ObsidianStatus {
  return {
    vaultPath: '',
    noteCount: 0,
    lastScanAt: null,
    lastError: null,
    ...over,
  }
}

function noteListFixture(): NoteListResponse {
  const note: NoteView = {
    ref: 'library:note-1',
    relPath: 'README.md',
    title: '欢迎笔记',
    tags: ['obsidian'],
    indexedAt: '2026-09-11T09:00:00Z',
    contentHtml: null,
    wikilinks: null,
  }
  return { items: [note] }
}

function rescanResultFixture(over: Partial<ObsidianRescanResult> = {}): ObsidianRescanResult {
  return {
    added: 1,
    changed: 2,
    removed: 0,
    renames: 1,
    skipped: 0,
    unchanged: 5,
    elapsedMs: 42,
    vaultPath: '/home/z/Vault',
    ...over,
  }
}

function searchResponseFixture(over: Partial<SearchResponse> = {}): SearchResponse {
  return {
    items: [],
    nextCursor: null,
    hasMore: false,
    elapsedMs: 3,
    index: { entryCount: 5, lastSyncedAt: '100', partial: false },
    ...over,
  }
}

function favoritesFixture(over: Partial<FavoritesResponse> = {}): FavoritesResponse {
  return {
    rss: [],
    library: [],
    libraryError: null,
    ...over,
  }
}

function rssEntryFixture(ref: string): EntryListItem {
  return {
    entryRef: ref,
    title: `文章 ${ref}`,
    feedTitle: '示例源',
    author: null,
    url: null,
    publishedAt: '2026-09-11T08:00:00Z',
    read: false,
    starred: true,
  }
}

function mailListsFixture(): MailBridgeListResponse {
  return {
    items: [{ uuid: 'list-1', name: '日记投递', createdAt: '2026-09-01T08:00:00Z' }],
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  useReaderUi.setState({
    section: 'home',
    view: 'all',
    scope: { kind: 'all' },
    selectedEntryRef: null,
    mobileSidebarOpen: false,
  })
  mocks.getFeeds.mockResolvedValue([])
  mocks.searchEntries.mockResolvedValue(searchResponseFixture())
  mocks.getEntries.mockResolvedValue({ items: [], nextCursor: null })
  mocks.getFavorites.mockResolvedValue(favoritesFixture())
  mocks.listApiSources.mockResolvedValue({ items: [] })
  mocks.listMailBridgeLists.mockResolvedValue(mailListsFixture())
  mocks.getDigestSettings.mockResolvedValue(digestSettingsFixture())
})

// ---- ApiSourcesSection ----

describe('ApiSourcesSection', () => {
  it('列表：名称 + endpoint host + lastStatus「正常」徽标', async () => {
    mocks.listApiSources.mockResolvedValue({ items: [apiSourceFixture()] })
    render(withProviders(<ApiSourcesSection />))
    expect(await screen.findByText('Hacker News API')).toBeInTheDocument()
    expect(screen.getByText('hacker-news.firebaseio.com')).toBeInTheDocument()
    expect(screen.getByText('正常')).toBeInTheDocument()
  })

  it('创建：一次性成功面板展示 atomPath + 复制按钮 + 仅显示一次提示', async () => {
    mocks.listApiSources.mockResolvedValue({ items: [] })
    mocks.createApiSource.mockResolvedValue(
      apiSourceFixture({
        uuid: 'src-new',
        name: '新来源',
        atomPath: '/feeds/api-sources/src-new.atom?secret=one-time',
        secret: 'one-time',
      }),
    )
    render(withProviders(<ApiSourcesSection />))
    fireEvent.click(await screen.findByRole('button', { name: '新增来源' }))
    fireEvent.change(screen.getByLabelText('名称'), { target: { value: '新来源' } })
    fireEvent.change(screen.getByLabelText('Endpoint'), {
      target: { value: 'https://api.example.com/items' },
    })
    fireEvent.change(screen.getByLabelText('items 表达式（JMESPath）'), {
      target: { value: 'items' },
    })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    expect(await screen.findByText('/feeds/api-sources/src-new.atom?secret=one-time')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '复制' })).toBeInTheDocument()
    expect(screen.getByText(/此地址仅显示一次/)).toBeInTheDocument()
    expect(mocks.createApiSource).toHaveBeenCalledWith(
      expect.objectContaining({
        name: '新来源',
        endpoint: 'https://api.example.com/items',
        itemsExpr: 'items',
      }),
    )
  })
})

// ---- MailSection ----

describe('MailSection', () => {
  it('摘要设置：保存 → PUT 携带表单值；密码框永不回显（值恒为空）', async () => {
    mocks.updateDigestSettings.mockResolvedValue(digestSettingsFixture())
    render(withProviders(<MailSection />))

    const host = (await screen.findByLabelText('SMTP 服务器')) as HTMLInputElement
    expect(host.value).toBe('smtp.example.com')
    const password = screen.getByLabelText('SMTP 密码') as HTMLInputElement
    expect(password.value).toBe('') // write-only：passwordConfigured=true 也不回显

    const smtpFormValue = 'test-typed' + '-value' // 非凭据：仅验证表单提交路径的表单值
    fireEvent.change(screen.getByLabelText('发送时刻'), { target: { value: '9' } })
    fireEvent.change(screen.getByLabelText('条数上限'), { target: { value: '7' } })
    fireEvent.change(password, { target: { value: smtpFormValue } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() =>
      expect(mocks.updateDigestSettings).toHaveBeenCalledWith(
        expect.objectContaining({
          hour: 9,
          limitCount: 7,
          smtpHost: 'smtp.example.com',
          smtpPassword: smtpFormValue,
        }),
      ),
    )
  })

  it('发送测试摘要（空选择）：BFF 错误 message 原样透出', async () => {
    mocks.sendDigestNow.mockRejectedValue(
      new ApiError(503, 'smtp_not_configured', 'SMTP 未配置，无法发送'),
    )
    render(withProviders(<MailSection />))
    fireEvent.click(await screen.findByRole('button', { name: '发送测试摘要' }))
    expect(await screen.findByText('SMTP 未配置，无法发送')).toBeInTheDocument()
    expect(mocks.sendDigestNow).toHaveBeenCalledWith([])
  })
})

// ---- ObsidianPage ----

describe('ObsidianPage', () => {
  it('未配置：输入 Vault 路径 → 连接调用 PUT settings', async () => {
    mocks.getObsidianStatus.mockResolvedValue(obsidianStatusFixture())
    mocks.updateObsidianSettings.mockResolvedValue({
      vaultPath: '/home/z/Vault',
      noteCount: 0,
    })
    render(withProviders(<ObsidianPage />))
    const input = await screen.findByLabelText('Vault 路径')
    fireEvent.change(input, { target: { value: '/home/z/Vault' } })
    fireEvent.click(screen.getByRole('button', { name: '连接' }))
    await waitFor(() =>
      expect(mocks.updateObsidianSettings).toHaveBeenCalledWith('/home/z/Vault'),
    )
  })

  it('已配置：状态行 + 笔记列表渲染；重扫报告行「新增/更改/删除/改名/跳过」', async () => {
    mocks.getObsidianStatus.mockResolvedValue(
      obsidianStatusFixture({
        vaultPath: '/home/z/Vault',
        noteCount: 6,
        lastScanAt: '2026-09-12T00:00:00Z',
      }),
    )
    mocks.listObsidianNotes.mockResolvedValue(noteListFixture())
    mocks.rescanObsidian.mockResolvedValue(rescanResultFixture())
    render(withProviders(<ObsidianPage />))

    expect(await screen.findByText('欢迎笔记')).toBeInTheDocument()
    expect(screen.getByText('README.md')).toBeInTheDocument()
    expect(screen.getByText('obsidian')).toBeInTheDocument()
    expect(screen.getByText(/6 条笔记/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '重扫' }))
    expect(await screen.findByText(/新增 1/)).toBeInTheDocument()
    expect(screen.getByText(/更改 2/)).toBeInTheDocument()
    expect(screen.getByText(/删除 0/)).toBeInTheDocument()
    expect(screen.getByText(/改名 1/)).toBeInTheDocument()
    expect(screen.getByText(/跳过 0/)).toBeInTheDocument()
    expect(mocks.rescanObsidian).toHaveBeenCalledTimes(1)
  })
})

// ---- SearchPage（库分组） ----

describe('SearchPage 库分组', () => {
  it('data.library 非空：RSS 结果之后渲染「库」分组（kind 徽标 + 片段）', async () => {
    mocks.searchEntries.mockResolvedValue(
      searchResponseFixture({
        library: [
          {
            ref: 'library:b1',
            kind: 'bookmark',
            title: '库书签标题',
            url: 'https://example.com/b',
            snippet: '库片段文本',
            updatedAt: '2026-09-11T10:00:00Z',
          },
        ],
        libraryError: null,
      }),
    )
    render(withProviders(<SearchPage />))
    const input = screen.getByRole('searchbox', { name: '搜索' })
    fireEvent.change(input, { target: { value: '关键词' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(await screen.findByRole('heading', { name: '库' })).toBeInTheDocument()
    expect(screen.getByText('库书签标题')).toBeInTheDocument()
    expect(screen.getByText('书签')).toBeInTheDocument()
    expect(screen.getByText('库片段文本')).toBeInTheDocument()
  })

  it('libraryError：小字诚实提示（不阻塞 RSS 结果区）', async () => {
    mocks.searchEntries.mockResolvedValue(
      searchResponseFixture({ library: [], libraryError: '库索引不可用' }),
    )
    render(withProviders(<SearchPage />))
    const input = screen.getByRole('searchbox', { name: '搜索' })
    fireEvent.change(input, { target: { value: '关键词' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(await screen.findByText(/库搜索暂不可用：库索引不可用/)).toBeInTheDocument()
  })
})

// ---- FavoritesPage（联合收藏） ----

describe('FavoritesPage 联合收藏', () => {
  it('两组渲染：RSS 收藏 + 库收藏；libraryError 诚实小字', async () => {
    mocks.getEntries.mockResolvedValue({
      items: [rssEntryFixture('e1.a')],
      nextCursor: null,
    })
    mocks.getFavorites.mockResolvedValue(
      favoritesFixture({
        library: [
          {
            ref: 'library:n1',
            kind: 'obsidian_note',
            title: '笔记收藏条目',
            url: 'https://example.com/note',
            snippet: '',
            updatedAt: '2026-09-11T10:00:00Z',
          },
        ],
        libraryError: '库索引超时',
      }),
    )
    render(withProviders(<FavoritesPage />))

    expect(await screen.findByText('RSS 收藏')).toBeInTheDocument()
    expect(screen.getByText('文章 e1.a')).toBeInTheDocument()
    expect(await screen.findByText('库收藏')).toBeInTheDocument()
    expect(screen.getByText('笔记收藏条目')).toBeInTheDocument()
    expect(screen.getByText('笔记')).toBeInTheDocument()
    expect(screen.getByText(/库索引暂不可用：库索引超时/)).toBeInTheDocument()
  })
})
