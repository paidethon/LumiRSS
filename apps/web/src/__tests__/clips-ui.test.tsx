/** phase2 Gate 3 — 网页剪藏 + 网页快照 Web UI 测试。
 *
 * - ClipsPage：列表行渲染（安全外链）/ 立即删除（行消失 + 正确 ref）；
 * - 剪藏流程：抓取 → 提取（mock extractArticle）→ createClip 收到
 *   提取 payload（提取时已过 DOMPurify）；成功文案「已保存「…」」；
 * - 提取失败：固定文案 +「只保存链接」以 url-only payload 落库；
 * - SnapshotsPage：配额行（role=status，人类可读）+
 *   monolith_unavailable 错误原样透出 message；
 * - Share Target：sessionStorage 'lumirss-share-url' 预填输入框并清除；
 * - Sidebar / 折叠 Rail：网页剪藏 / 网页快照 section 导航激活；
 * - ReaderHeader：保存快照仅绝对 http(s) 原文渲染 + createSnapshot 调用。
 *
 * 统一 vi.mock('../api/client')（保留 ApiError 等真实导出）+
 * vi.mock('../lib/clip-extract')（避免测试加载 defuddle/readability）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type {
  Clip,
  ClipDetail,
  EntryDetail,
  SnapshotListResponse,
  SnapshotUsage,
} from '../api/types'
import { ApiError } from '../api/client'
import ClipsPage from '../components/pages/ClipsPage'
import SnapshotsPage from '../components/pages/SnapshotsPage'
import Sidebar from '../components/Sidebar'
import SidebarCollapsedRail from '../components/SidebarCollapsedRail'
import ReaderHeader from '../components/ReaderHeader'
import { useReaderUi } from '../store/reader-ui'

const mocks = vi.hoisted(() => ({
  getFeeds: vi.fn(),
  fetchClipHtml: vi.fn(),
  createClip: vi.fn(),
  listClips: vi.fn(),
  getClip: vi.fn(),
  deleteClip: vi.fn(),
  listSnapshots: vi.fn(),
  createSnapshot: vi.fn(),
  deleteSnapshot: vi.fn(),
  extractArticle: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getFeeds: mocks.getFeeds,
    fetchClipHtml: mocks.fetchClipHtml,
    createClip: mocks.createClip,
    listClips: mocks.listClips,
    getClip: mocks.getClip,
    deleteClip: mocks.deleteClip,
    listSnapshots: mocks.listSnapshots,
    createSnapshot: mocks.createSnapshot,
    deleteSnapshot: mocks.deleteSnapshot,
  }
})

vi.mock('../lib/clip-extract', () => ({
  extractArticle: mocks.extractArticle,
}))

function clipFixture(ref: string, over: Partial<Clip> = {}): Clip {
  return {
    ref,
    url: `https://example.com/${ref}`,
    title: `剪藏 ${ref}`,
    byline: null,
    createdAt: '2026-09-01T08:00:00Z',
    fetchedAt: '2026-09-01T08:00:00Z',
    ...over,
  }
}

function clipDetailFixture(ref: string, over: Partial<ClipDetail> = {}): ClipDetail {
  return {
    ...clipFixture(ref, over),
    contentHtml: '<p>正文</p>',
    contentText: '正文',
  }
}

function snapshotListFixture(usage: Partial<SnapshotUsage> = {}): SnapshotListResponse {
  return {
    items: [
      {
        uuid: 'snap0001-uuid',
        itemRef: 'library:snap0001-uuid',
        url: 'https://example.com/page',
        bytes: 2048,
        sha256: 'a'.repeat(64),
        deduplicated: false,
        createdAt: '2026-09-01T08:00:00Z',
      },
    ],
    usage: { count: 1, bytes: 2048, quotaBytes: 104857600, ...usage },
  }
}

function entryDetailFixture(url: string | null): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '文章',
    feedTitle: '源',
    author: null,
    url,
    publishedAt: null,
    read: false,
    starred: false,
    contentText: '',
    contentHtml: null,
  }
}

function withProviders(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  useReaderUi.setState({
    section: 'home',
    view: 'all',
    scope: { kind: 'all' },
    selectedEntryRef: null,
    mobileSidebarOpen: false,
  })
  mocks.listClips.mockResolvedValue({ items: [], nextCursor: null })
  mocks.listSnapshots.mockResolvedValue(snapshotListFixture())
  mocks.createSnapshot.mockResolvedValue(snapshotListFixture().items[0])
  mocks.getFeeds.mockResolvedValue([])
})

describe('ClipsPage', () => {
  it('列表：行渲染（标题安全外链）+ 立即删除（行消失 + 正确 ref）', async () => {
    mocks.listClips
      .mockResolvedValueOnce({
        items: [clipFixture('library:c1'), clipFixture('library:c2')],
        nextCursor: null,
      })
      .mockResolvedValue({ items: [clipFixture('library:c1')], nextCursor: null })
    render(withProviders(<ClipsPage />))
    expect(await screen.findByText('剪藏 library:c1')).toBeInTheDocument()
    expect(screen.getByText('剪藏 library:c2')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'https://example.com/library:c1' })
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')

    const row = screen.getByText('剪藏 library:c2').closest('article')
    expect(row).not.toBeNull()
    fireEvent.click(within(row as HTMLElement).getByRole('button', { name: '删除剪藏' }))
    await waitFor(() => expect(screen.queryByText('剪藏 library:c2')).toBeNull())
    expect(mocks.deleteClip).toHaveBeenCalledWith('library:c2')
  })

  it('剪藏流程：抓取 → 提取 → createClip 收到提取 payload + 成功文案', async () => {
    mocks.fetchClipHtml.mockResolvedValue({
      url: 'https://example.com/a',
      finalUrl: 'https://example.com/a',
      html: '<html><body><article>正文</article></body></html>',
    })
    mocks.extractArticle.mockResolvedValue({
      title: '提取标题',
      byline: '作者',
      contentHtml: '<p>正文段落</p>',
      contentText: '正文段落',
    })
    mocks.createClip.mockResolvedValue(
      clipDetailFixture('library:n1', {
        url: 'https://example.com/a',
        title: '提取标题',
        byline: '作者',
        contentHtml: '<p>正文段落</p>',
        contentText: '正文段落',
      }),
    )
    render(withProviders(<ClipsPage />))
    fireEvent.change(screen.getByLabelText('粘贴链接'), {
      target: { value: 'https://example.com/a' },
    })
    fireEvent.click(screen.getByRole('button', { name: '剪藏' }))
    expect(await screen.findByText('已保存「提取标题」')).toBeInTheDocument()
    expect(mocks.fetchClipHtml).toHaveBeenCalledWith('https://example.com/a')
    expect(mocks.createClip).toHaveBeenCalledWith(
      expect.objectContaining({
        url: 'https://example.com/a',
        title: '提取标题',
        byline: '作者',
        contentHtml: '<p>正文段落</p>',
        contentText: '正文段落',
      }),
    )
  })

  it('提取失败：固定文案 + 「只保存链接」以 url-only payload 落库', async () => {
    mocks.fetchClipHtml.mockResolvedValue({
      url: 'https://example.com/b',
      finalUrl: 'https://example.com/b',
      html: '<html></html>',
    })
    mocks.extractArticle.mockRejectedValue(new Error('boom'))
    mocks.createClip.mockResolvedValue(
      clipDetailFixture('library:n2', {
        url: 'https://example.com/b',
        title: 'https://example.com/b',
        contentHtml: '<p>https://example.com/b</p>',
        contentText: 'https://example.com/b',
      }),
    )
    render(withProviders(<ClipsPage />))
    fireEvent.change(screen.getByLabelText('粘贴链接'), {
      target: { value: 'https://example.com/b' },
    })
    fireEvent.click(screen.getByRole('button', { name: '剪藏' }))
    expect(await screen.findByText('正文提取失败：可重试或只保存链接。')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '只保存链接' }))
    expect(await screen.findByText('已保存「https://example.com/b」')).toBeInTheDocument()
    expect(mocks.createClip).toHaveBeenLastCalledWith(
      expect.objectContaining({
        url: 'https://example.com/b',
        title: 'https://example.com/b',
        contentHtml: '<p>https://example.com/b</p>',
        contentText: 'https://example.com/b',
      }),
    )
  })

  it('Share Target：sessionStorage lumirss-share-url 预填输入框并清除', () => {
    sessionStorage.setItem('lumirss-share-url', 'https://example.com/shared')
    render(withProviders(<ClipsPage />))
    const input = screen.getByLabelText('粘贴链接') as HTMLInputElement
    expect(input.value).toBe('https://example.com/shared')
    expect(sessionStorage.getItem('lumirss-share-url')).toBeNull()
  })
})

describe('SnapshotsPage', () => {
  it('配额行（role=status，人类可读）+ 列表行渲染', async () => {
    render(withProviders(<SnapshotsPage />))
    const quota = await screen.findByText('已用 2 KB / 配额 100 MB')
    expect(quota).toHaveAttribute('role', 'status')
    expect(screen.getByText('snap0001')).toBeInTheDocument()
    const open = screen.getByRole('link', { name: '打开原文快照' })
    expect(open).toHaveAttribute(
      'href',
      '/api/v1/library/assets/snap0001-uuid/page.html',
    )
    expect(open).toHaveAttribute('target', '_blank')
    expect(open).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('monolith_unavailable 错误原样透出 message', async () => {
    mocks.listSnapshots.mockRejectedValue(
      new ApiError(503, 'monolith_unavailable', 'monolith 未安装，无法生成快照'),
    )
    render(withProviders(<SnapshotsPage />))
    expect(await screen.findByText('monolith 未安装，无法生成快照')).toBeInTheDocument()
  })
})

describe('Sidebar / 折叠 Rail / ReaderHeader', () => {
  it('侧栏 + 折叠 Rail：网页剪藏 / 网页快照 section 导航激活', () => {
    const sidebar = render(withProviders(<Sidebar />))
    fireEvent.click(screen.getByRole('button', { name: '网页剪藏' }))
    expect(useReaderUi.getState().section).toBe('clips')
    fireEvent.click(screen.getByRole('button', { name: '网页快照' }))
    expect(useReaderUi.getState().section).toBe('snapshots')
    sidebar.unmount()

    const rail = render(<SidebarCollapsedRail />)
    fireEvent.click(screen.getByRole('button', { name: '网页剪藏' }))
    expect(useReaderUi.getState().section).toBe('clips')
    fireEvent.click(screen.getByRole('button', { name: '网页快照' }))
    expect(useReaderUi.getState().section).toBe('snapshots')
    rail.unmount()
  })

  it('ReaderHeader 保存快照：仅绝对 http(s) 原文渲染；点击调用 createSnapshot', async () => {
    const { rerender } = render(
      withProviders(<ReaderHeader detail={entryDetailFixture('https://example.com/a')} />),
    )
    fireEvent.click(screen.getByRole('button', { name: '保存快照' }))
    await waitFor(() =>
      expect(mocks.createSnapshot).toHaveBeenCalledWith('https://example.com/a'),
    )

    rerender(withProviders(<ReaderHeader detail={entryDetailFixture('/relative/only')} />))
    expect(screen.queryByRole('button', { name: '保存快照' })).toBeNull()
  })
})
