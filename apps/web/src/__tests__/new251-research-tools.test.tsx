/** NEW-251..260 Web 入口测试 — 研究项目工具组容器 + 结论史(259)/分享预览(260) 主路径。
 *
 * 环境：jsdom；fetch 按 URL 匹配 mock（服务真源在 BFF，后端口径见
 * tests/test_new25*.py / test_new260*.py）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { New251ResearchTools } from '../components/new251/New251ResearchTools'

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

const fetchCalls: { url: string; init?: RequestInit }[] = []
let routes: {
  match: (url: string, init?: RequestInit) => boolean
  respond: (url: string, init?: RequestInit) => Response
}[] = []

function mockRoute(
  matcher: (url: string, init?: RequestInit) => boolean,
  responder: (url: string, init?: RequestInit) => Response,
): void {
  routes.push({ match: matcher, respond: responder })
}

beforeEach(() => {
  fetchCalls.length = 0
  routes = []
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    fetchCalls.push({ url, init })
    for (const route of routes) {
      if (route.match(url, init)) return route.respond(url, init)
    }
    return jsonResponse({ error: { type: 'unmocked', message: url } }, 404)
  }) as typeof fetch
})

afterEach(() => {
  cleanup()
  routes = []
})

const PROJECTS = {
  items: [{ id: 'p-1', title: '水厂改造考证', description: null, createdAt: 't', updatedAt: 't' }],
}

function mockProjectLine(): void {
  mockRoute(
    (url, init) => url === '/api/v1/research/projects' && (init?.method ?? 'GET') === 'GET',
    () => jsonResponse(PROJECTS),
  )  // 子面板 GET 一律回空表，避免 404 噪音（各自专项在 BFF 测试覆盖）。
  for (const path of [
    '/api/v1/research/projects/p-1/questions',
    '/api/v1/research/projects/p-1/hypotheses',
    '/api/v1/research/projects/p-1/counterexamples',
    '/api/v1/research/projects/p-1/glossary',
    '/api/v1/research/projects/p-1/timeline',
    '/api/v1/research/projects/p-1/decisions',
    '/api/v1/research/projects/p-1/gaps',
    '/api/v1/research/projects/p-1/share-confirmations',
  ]) {
    mockRoute((url, init) => url === path && (init?.method ?? 'GET') === 'GET', () => jsonResponse({ projectId: 'p-1', items: [] }))
  }
  mockRoute(
    (url, init) => url === '/api/v1/research/projects/p-1/outline' && (init?.method ?? 'GET') === 'GET',
    () =>
      jsonResponse({
        projectId: 'p-1',
        sections: [],
        note: '无章节。',
      }),
  )
}

async function expandAndSelectProject(): Promise<void> {
  mockProjectLine()
  renderWithQuery(<New251ResearchTools />)
  fireEvent.click(screen.getByRole('button', { name: /研究项目工具（/ }))
  await waitFor(() => expect(fetchCalls.some((c) => c.url === '/api/v1/research/projects')).toBe(true))
  await screen.findByText('水厂改造考证')
  fireEvent.change(screen.getByLabelText('当前研究项目'), { target: { value: 'p-1' } })
  await waitFor(() =>
    expect(fetchCalls.some((c) => c.url === '/api/v1/research/projects/p-1/questions')).toBe(true),
  )
}

describe('NEW-251..260 研究项目工具组（New251ResearchTools）', () => {
  it('折叠态零查询；展开后 aria-expanded 翻转并发出项目列表请求', async () => {
    renderWithQuery(<New251ResearchTools />)
    const toggle = screen.getByRole('button', { name: /研究项目工具（/ })
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(fetchCalls.length).toBe(0)
    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    await waitFor(() => expect(fetchCalls.some((c) => c.url === '/api/v1/research/projects')).toBe(true))
  })

  it('NEW-251 选中项目后挂载子面板：问题拆分面板可见并发起查询；创建项目走 POST', async () => {
    await expandAndSelectProject()
    expect(screen.getByLabelText('新建研究项目')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('新建研究项目'), { target: { value: '第二个项目' } })
    mockRoute(
      (url, init) => url === '/api/v1/research/projects' && init?.method === 'POST',
      () =>
        jsonResponse({
          id: 'p-2',
          title: '第二个项目',
          description: null,
          createdAt: 't',
          updatedAt: 't',
        }),
    )
    fireEvent.click(screen.getByRole('button', { name: '创建项目' }))
    await waitFor(() =>
      expect(fetchCalls.some((c) => c.url === '/api/v1/research/projects' && c.init?.method === 'POST')).toBe(true),
    )
  })

  it('NEW-259 登记新结论走 PUT 且历史台账渲染原结论（不覆盖）', async () => {
  mockRoute(
    (url) => url === '/api/v1/research/projects/p-1/conclusion/history',
    () =>
        jsonResponse({
          projectId: 'p-1',
          historyCount: 1,
          items: [
            {
              id: 'ch-1',
              projectId: 'p-1',
              oldText: null,
              newText: '改造完成于 1935 年前',
              triggerRefs: ['library:m-1'],
              reason: '初次登记',
              changedAt: '2026-09-28T10:00:00+00:00',
            },
          ],
        }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/research/projects/p-1/conclusion' && (init?.method ?? 'GET') === 'GET',
      () => jsonResponse({ projectId: 'p-1', text: '改造完成于 1935 年前', updatedAt: 't', historyCount: 1 }),
    )
    await expandAndSelectProject()
    expect(await screen.findByText(/原结论：（此前未登记）/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText(/新结论（手写文本/), {
      target: { value: '更正：改造完成于 1934 年冬' },
    })
    fireEvent.change(screen.getByLabelText(/触发材料 ItemRef/), {
      target: { value: 'library:m-2' },
    })
    mockRoute(
      (url, init) => url === '/api/v1/research/projects/p-1/conclusion' && init?.method === 'PUT',
      () =>
        jsonResponse({
          projectId: 'p-1',
          text: '更正：改造完成于 1934 年冬',
          updatedAt: 't',
          historyCount: 2,
          previousText: '改造完成于 1935 年前',
          latestChange: {
            id: 'ch-2',
            projectId: 'p-1',
            oldText: '改造完成于 1935 年前',
            newText: '更正：改造完成于 1934 年冬',
            triggerRefs: ['library:m-2'],
            reason: null,
            changedAt: '2026-09-28T11:00:00+00:00',
          },
        }),
    )
    fireEvent.click(screen.getByRole('button', { name: '登记新结论' }))
    await waitFor(() => {
      const put = fetchCalls.find(
        (c) => c.url === '/api/v1/research/projects/p-1/conclusion' && c.init?.method === 'PUT',
      )
      expect(put).toBeTruthy()
      expect(JSON.parse(String(put?.init?.body))).toEqual({
        text: '更正：改造完成于 1934 年冬',
        triggerRefs: ['library:m-2'],
      })
    })
    expect(await screen.findByText(/原结论保留在台账/)).toBeTruthy()
  })

  it('NEW-260 盘点私人笔记/成员名逐项勾选，确认快照按勾选发送；附件区诚实为空', async () => {
    mockRoute(
      (url, init) => url === '/api/v1/research/projects/p-1/share-preview' && (init?.method ?? 'GET') === 'GET',
      () =>
        jsonResponse({
          projectId: 'p-1',
          privateNotes: [
            { id: 'n-1', table: 'research_hypothesis_materials', field: 'note', itemId: 'hm-1', excerpt: '私下猜测：底片编号存疑' },
          ],
          memberNames: [
            {
              username: 'alice',
              occurrences: [{ id: 'o-1', table: 'research_counterexamples', field: 'note', itemId: 'c-1', excerpt: 'alice 提供的线索' }],
            },
          ],
          attachments: [],
          attachmentsNote: '研究组各表不存附件。',
          note: '盘点只读。',
        }),
    )
    await expandAndSelectProject()
    expect(await screen.findByText(/研究组各表不存附件/)).toBeTruthy()
    const noteCheck = screen.getByLabelText('允许带出私人笔记（research_hypothesis_materials.note）') as HTMLInputElement
    const nameCheck = screen.getByLabelText('匿名化成员名 alice') as HTMLInputElement
    expect(noteCheck.checked).toBe(false)
    fireEvent.click(noteCheck)
    fireEvent.click(nameCheck)
    expect(noteCheck.checked).toBe(true)
    mockRoute(
      (url, init) => url === '/api/v1/research/projects/p-1/share-confirmations' && init?.method === 'POST',
      () =>
        jsonResponse({
          id: 'sc-1',
          projectId: 'p-1',
          manifest: {
            includePrivateNoteIds: ['n-1'],
            anonymizeMemberUsernames: ['alice'],
            privateNoteCountAtConfirm: 1,
            memberNameHitCountAtConfirm: 1,
          },
          createdAt: '2026-09-28T12:00:00+00:00',
        }),
    )
    fireEvent.click(screen.getByRole('button', { name: '存确认快照' }))
    await waitFor(() => {
      const post = fetchCalls.find(
        (c) => c.url === '/api/v1/research/projects/p-1/share-confirmations' && c.init?.method === 'POST',
      )
      expect(post).toBeTruthy()
      expect(JSON.parse(String(post?.init?.body))).toEqual({
        includePrivateNoteIds: ['n-1'],
        anonymizeMemberUsernames: ['alice'],
      })
    })
    expect(await screen.findByText(/已存确认快照/)).toBeTruthy()
  })
})
