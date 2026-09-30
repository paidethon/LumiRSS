/** NEW-399 帮助文档反馈定位 — 用户提交与处理结果 + 管理员队列（Web 入口；
 * 服务真源在 BFF tests/test_new399_doc_feedback.py）。 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  AdminDocFeedbackQueue,
  DocFeedbackPanel,
} from '../components/new391/DocFeedbackPanel'

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

const calls: { url: string; init?: RequestInit }[] = []
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
  calls.length = 0
  routes = []
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    calls.push({ url, init })
    for (const route of routes) {
      if (route.match(url, init)) return route.respond(url, init)
    }
    return jsonResponse({ error: { type: 'not_mocked', message: url } }, 404)
  }) as typeof fetch
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('NEW-399 用户侧反馈', () => {
  it('提交携带 docPath/锚点/问题；本人列表显示版本与处理结果', async () => {
    mockRoute(
      (url, init) => url === '/api/v1/help/feedback' && init?.method === 'POST',
      () =>
        jsonResponse({
          id: 'f1', docPath: 'README.md', anchor: '架构',
          anchorFound: true, version: '2.0.1', question: '这节过时了。',
          status: 'open', revisionNote: '', reply: '', createdAt: 'TP',
          resolvedAt: null,
        }, 201),
    )
    mockRoute(
      (url) => url === '/api/v1/help/feedback',
      () =>
        jsonResponse({
          items: [
            {
              id: 'f0', docPath: 'getting-started.md', anchor: '安装',
              anchorFound: false, version: '2.0.0', question: '步骤缺一步。',
              status: 'revised', revisionNote: '§安装按 2.0 重写。',
              reply: '已修订，请再看。', createdAt: 'TP', resolvedAt: 'TP',
            },
          ],
        }),
    )
    renderWithQuery(<DocFeedbackPanel />)
    fireEvent.change(await screen.findByLabelText('文档路径（相对 docs/）'), {
      target: { value: 'README.md' },
    })
    fireEvent.change(screen.getByLabelText('锚点 / 小节标题（可选）'), {
      target: { value: '架构' },
    })
    fireEvent.change(screen.getByLabelText('你的问题'), {
      target: { value: '这节过时了。' },
    })
    fireEvent.click(screen.getByRole('button', { name: '提交反馈' }))
    await waitFor(() => {
      const post = calls.find(
        (call) => call.url === '/api/v1/help/feedback' && call.init?.method === 'POST',
      )
      expect(post).toBeDefined()
      expect(JSON.parse(String(post!.init?.body))).toEqual({
        docPath: 'README.md', anchor: '架构', question: '这节过时了。',
      })
    })
    // 列表渲染：版本锚点定位 + 锚点未找到的诚实标注 + 修订回复
    expect(screen.getByText(/getting-started\.md #安装/)).toBeInTheDocument()
    expect(screen.getByText('锚点在当前文档里未找到（仍已提交）。')).toBeInTheDocument()
    expect(screen.getByText(/修订说明：§安装按 2.0 重写。/)).toBeInTheDocument()
  })
})

describe('NEW-399 管理员队列', () => {
  it('列出待处理反馈（含版本）；修订回复发 resolve', async () => {
    mockRoute(
      (url) => url === '/api/v1/admin/help/feedback?status=open',
      () =>
        jsonResponse({
          items: [
            {
              id: 'f1', docPath: 'README.md', anchor: '架构',
              anchorFound: true, version: '2.0.1', question: '这节过时了。',
              status: 'open', revisionNote: '', reply: '', createdAt: 'TP',
              resolvedAt: null,
            },
          ],
        }),
    )
    mockRoute(
      (url, init) =>
        url === '/api/v1/admin/help/feedback/f1/resolve' && init?.method === 'POST',
      () =>
        jsonResponse({
          id: 'f1', status: 'revised', revisionNote: '已重写。', reply: '请再看。',
          resolvedAt: 'TP', docPath: 'README.md', anchor: '架构',
          anchorFound: true, version: '2.0.1', question: '这节过时了。', createdAt: 'TP',
        }),
    )
    renderWithQuery(<AdminDocFeedbackQueue />)
    expect(await screen.findByText(/README\.md #架构 · v2\.0\.1/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('修订说明'), {
      target: { value: '已重写。' },
    })
    fireEvent.change(screen.getByLabelText('回复作者'), {
      target: { value: '请再看。' },
    })
    fireEvent.click(screen.getByRole('button', { name: '标记已修订并回复' }))
    await waitFor(() => {
      const post = calls.find((call) => call.url.endsWith('/resolve'))
      expect(post).toBeDefined()
      expect(JSON.parse(String(post!.init?.body))).toEqual({
        revisionNote: '已重写。', reply: '请再看。',
      })
    })
  })
})
