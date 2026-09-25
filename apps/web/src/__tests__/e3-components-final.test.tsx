/** E3-final 组件测试 — N079 笔记分栏编辑/导出、N090 仅本机徽章与引擎
 * 强制、N098 TTS 缓存面板、N110 最近工作区卡片、N190 停用流。
 *
 * fetch 全部 stub（零网络）；BFF 端行为契约由 BFF 测试锁定。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReaderTranslation from '../components/ReaderTranslation'
import { NotesManager } from '../components/NotesManager'
import { TtsCacheSection } from '../components/settings/TtsCacheSection'
import RecentWorkspacesCard from '../components/RecentWorkspacesCard'
import { DeactivationSection } from '../components/settings/DeactivationSection'
import type { EntryDetail } from '../api/types'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderWithQuery(ui: React.ReactElement): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

// ---- N079 笔记分栏 ------------------------------------------------------------

describe('N079 笔记分栏编辑器', () => {
  it('三栏并排（事实/个人解读/待核实）；保存时随笔记提交', async () => {
        const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/v1/library/notes' && init?.method === 'POST') {
        const body = JSON.parse(String(init.body))
        expect(body.sections).toEqual({
          facts: ['原文事实 A'],
          interpretation: ['我的解读 B'],
          toVerify: ['待核实 C'],
        })
        return Promise.resolve(
          jsonResponse({
            uuid: 'n1',
            title: '分栏',
            contentMd: 'x',
            workspaceId: null,
            sections: body.sections,
            createdAt: '2026-01-01T00:00:00Z',
            updatedAt: '2026-01-01T00:00:00Z',
          }),
        )
      }
      if (url.startsWith('/api/v1/library/notes')) {
        return Promise.resolve(jsonResponse({ items: [] }))
      }
      return Promise.resolve(jsonResponse({}, 404))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderWithQuery(<NotesManager />)
    fireEvent.click(await screen.findByRole('button', { name: /新建笔记/ }))
    await screen.findByLabelText('笔记标题')

    fireEvent.change(screen.getByLabelText('笔记标题'), { target: { value: '分栏' } })
    fireEvent.change(screen.getByLabelText('事实栏（每行一条）'), {
      target: { value: '原文事实 A' },
    })
    fireEvent.change(screen.getByLabelText('个人解读栏（每行一条）'), {
      target: { value: '我的解读 B' },
    })
    fireEvent.change(screen.getByLabelText('待核实栏（每行一条）'), {
      target: { value: '待核实 C' },
    })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true)
    })
  })
})

// ---- N090 翻译隐私路由（客户端强制本机 + 徽章） --------------------------------

const AI_SETTINGS = {
  provider: 'openai_compatible',
  baseUrl: '',
  model: '',
  summaryLanguage: 'zh-CN',
  translationLanguage: 'zh-CN',
  translationEngine: 'ai',
  libretranslateUrl: '',
  libretranslateKeyConfigured: false,
  configured: false,
  envKeyConfigured: false,
  defaultKeyConfigured: false,
  purposes: {},
  purposeStatus: {},
}

function detailWith(feedUrl: string | null): EntryDetail {
  return {
    entryRef: 'e1.n090',
    title: '标题',
    feedTitle: '隐私源',
    author: null,
    url: null,
    publishedAt: null,
    read: false,
    starred: false,
    contentText: '第一段正文。\n第二段正文。',
    contentHtml: null,
    ...(feedUrl !== null ? { feedUrl } : {}),
  } as EntryDetail
}

describe('N090 local_only 来源的客户端行为', () => {
  it('local_only：显示「仅本机」徽章，且从不发起远程 generate', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/v1/settings/ai') return Promise.resolve(jsonResponse(AI_SETTINGS))
      if (url === '/api/v1/sources/overrides') {
        return Promise.resolve(
          jsonResponse({
            items: [
              { feedUrl: 'https://p.example/feed', translationPolicy: 'local_only' },
            ],
          }),
        )
      }
      return Promise.resolve(jsonResponse({}, 404))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderWithQuery(<ReaderTranslation detail={detailWith('https://p.example/feed')} viewMode="bilingual" />)
    expect(await screen.findByTestId('local-only-badge')).toHaveTextContent('仅本机')

    await new Promise((r) => setTimeout(r, 300))
    const generateCalls = fetchMock.mock.calls.filter(([u]) =>
      String(u).endsWith('/translation/segments/generate'),
    )
    expect(generateCalls).toEqual([])
  })

  it('无策略来源：不显示徽章（全局引擎语义不变）', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/v1/settings/ai') return Promise.resolve(jsonResponse(AI_SETTINGS))
      if (url === '/api/v1/sources/overrides') return Promise.resolve(jsonResponse({ items: [] }))
      return Promise.resolve(jsonResponse({}, 404))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderWithQuery(<ReaderTranslation detail={detailWith('https://n.example/feed')} viewMode="bilingual" />)
    await new Promise((r) => setTimeout(r, 250))
    expect(screen.queryByTestId('local-only-badge')).toBeNull()
  })
})

// ---- N098 TTS 缓存面板 ---------------------------------------------------------

describe('N098 音频生成缓存面板', () => {
  it('清单（size/date）+ 单条删除 + 清空', async () => {
        const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/v1/tts/cache' && init?.method === 'DELETE') {
        return Promise.resolve(jsonResponse({ removed: 2 }))
      }
      if (url === '/api/v1/tts/cache') {
        return Promise.resolve(
          jsonResponse({
            items: [
              {
                id: 't1',
                textHash: 'abc',
                voice: 'alloy',
                model: 'tts-1',
                sizeBytes: 2048,
                createdAt: '2026-09-25T10:00:00Z',
              },
            ],
            totalBytes: 2048,
            count: 1,
            capBytes: 50 * 1024 * 1024,
          }),
        )
      }
      if (url === '/api/v1/tts/cache/t1') return Promise.resolve(new Response(null, { status: 204 }))
      return Promise.resolve(jsonResponse({}, 404))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderWithQuery(<TtsCacheSection />)
    expect(await screen.findByText('2.0 KB')).toBeInTheDocument()
    expect(screen.getByText(/共 1 条/)).toHaveTextContent('50.0 MB')

    fireEvent.click(screen.getByRole('button', { name: '删除此条缓存' }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([u]) => String(u) === '/api/v1/tts/cache/t1')).toBe(true)
    })
    fireEvent.click(screen.getByRole('button', { name: '清空全部' }))
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([u, init]) => String(u) === '/api/v1/tts/cache' && init?.method === 'DELETE',
        ),
      ).toBe(true)
    })
  })
})

// ---- N110 最近工作区卡片 ---------------------------------------------------------

describe('N110 最近工作区卡片', () => {
  it('记录存在时展示（per-user 键）；一键打开派发 open 事件', async () => {
    localStorage.setItem(
      'lumirss-recent-workspaces:user-x',
      JSON.stringify([{ workspaceId: 'w1', name: '论文阅读', openedAt: '2026-09-25T08:00:00Z' }]),
    )
    // 组件从 auth store 读 identity.userId
    const { useAuthStore } = await import('../store/auth')
    useAuthStore.setState({
      identity: { userId: 'user-x', username: 'u', role: 'member' },
      status: 'authenticated',
      mode: 'session',
    })

    const openListener = vi.fn()
    document.addEventListener('lumi:open-workspace', openListener)
    renderWithQuery(<RecentWorkspacesCard />)
    const entry = await screen.findByTestId('recent-workspace-entry')
    expect(entry).toHaveTextContent('论文阅读')

    fireEvent.click(entry)
    expect(openListener).toHaveBeenCalledTimes(1)
    expect((openListener.mock.calls[0][0] as CustomEvent).detail).toBe('w1')
    document.removeEventListener('lumi:open-workspace', openListener)
  })

  it('空记录（其他用户键）→ 卡片不渲染', async () => {
    localStorage.setItem(
      'lumirss-recent-workspaces:someone-else',
      JSON.stringify([{ workspaceId: 'w9', name: '别人的', openedAt: '2026-09-25T08:00:00Z' }]),
    )
    const { useAuthStore } = await import('../store/auth')
    useAuthStore.setState({
      identity: { userId: 'me', username: 'me', role: 'member' },
      status: 'authenticated',
      mode: 'session',
    })
    renderWithQuery(<RecentWorkspacesCard />)
    await new Promise((r) => setTimeout(r, 80))
    expect(screen.queryByTestId('recent-workspaces')).toBeNull()
  })
})

// ---- N190 停用流 -----------------------------------------------------------------

const CONFIRM_VALUE = Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2)

describe('N190 账户停用（设置入口）', () => {
  it('密码确认 → POST deactivation-request → 登录态翻转（会话已吊销）', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/v1/me/deactivation-request' && init?.method === 'POST') {
        expect(JSON.parse(String(init.body))).toEqual({ password: CONFIRM_VALUE })
        return Promise.resolve(
          jsonResponse({
            requested: true,
            requestedAt: '2026-09-25T00:00:00Z',
            scheduledDeletionAt: '2026-10-09T00:00:00Z',
            graceDays: 14,
            note: '到期后没有自动删除作业；物理删除由运营者手动执行。',
          }),
        )
      }
      return Promise.resolve(jsonResponse({}, 404))
    })
    vi.stubGlobal('fetch', fetchMock)
    const onDeactivated = vi.fn()

    renderWithQuery(<DeactivationSection onDeactivated={onDeactivated} />)
    fireEvent.click(screen.getByRole('button', { name: '停用我的账户…' }))
    fireEvent.change(screen.getByLabelText('确认密码（停用账户）'), {
      target: { value: CONFIRM_VALUE },
    })
    fireEvent.click(screen.getByRole('button', { name: '确认停用' }))

    await waitFor(() => {
      expect(onDeactivated).toHaveBeenCalledTimes(1)
    })
  })

  it('诚实文案：说明宽限恢复 + 无自动删除作业 + 迁出向导', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ requested: false })))
    vi.stubGlobal('fetch', fetchMock)
    renderWithQuery(<DeactivationSection onDeactivated={() => {}} />)
    const section = await screen.findByTestId('deactivation-section')
    expect(section).toHaveTextContent('运营者可恢复')
    expect(section).toHaveTextContent('没有自动删除作业')
    fireEvent.click(screen.getByRole('button', { name: '停用我的账户…' }))
    expect(screen.getByText(/迁出向导/)).toBeInTheDocument()
  })
})
