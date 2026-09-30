/** NEW-395/396 体验清单与回退偏好 — Web 入口测试（真实清单消费、
 * 覆盖式标记、兼容期限展示；服务真源在 BFF tests）。 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ExperienceChecklistPanel } from '../components/new391/ExperienceChecklistPanel'
import { InteractionModePrefsPanel } from '../components/new391/InteractionModePrefsPanel'

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

describe('NEW-395 体验清单', () => {
  it('展示实际上线功能与既有标记；标记「了解」发 POST', async () => {
    mockRoute(
      (url) => url === '/api/v1/whats-new/experience',
      () =>
        jsonResponse({
          version: '2.0.1',
          features: [
            {
              id: 'N041',
              title: '今日必读队列',
              entry: '/',
              adminOnly: false,
              mark: null,
            },
            {
              id: 'N195',
              title: '升级影响预览',
              entry: '/admin',
              adminOnly: true,
              mark: { status: 'later', updatedAt: 'TP' },
            },
          ],
        }),
    )
    mockRoute(
      (url, init) =>
        url === '/api/v1/whats-new/experience/N041/mark' && init?.method === 'POST',
      () => jsonResponse({ featureId: 'N041', status: 'learned', updatedAt: 'TP' }),
    )
    renderWithQuery(<ExperienceChecklistPanel />)
    expect(await screen.findByText('版本 2.0.1 实际上线的功能（按当前角色过滤）；标记只保存在本人账户。')).toBeInTheDocument()
    expect(screen.getByText('今日必读队列')).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: '我了解了' })[0]!)
    await waitFor(() => {
      const post = calls.find((call) => call.url.endsWith('/N041/mark'))
      expect(post).toBeDefined()
      expect(JSON.parse(String(post!.init?.body))).toEqual({ status: 'learned' })
    })
  })

  it('清单不可用时如实说明，绝不编造条目', async () => {
    mockRoute(
      (url) => url === '/api/v1/whats-new/experience',
      () => jsonResponse({ version: null, features: [], note: '发布清单不可用，无法展示体验清单。' }),
    )
    renderWithQuery(<ExperienceChecklistPanel />)
    expect(await screen.findByText('发布清单不可用，无法展示体验清单。')).toBeInTheDocument()
    expect(screen.queryByText(/我了解了/)).toBeNull()
  })
})

describe('NEW-396 回退偏好', () => {
  it('显示新旧两态与兼容期限；选择旧交互发 PUT', async () => {
    mockRoute(
      (url) => url === '/api/v1/interaction-modes',
      () =>
        jsonResponse({
          surfaces: [
            {
              key: 'search_advanced',
              label: '搜索交互',
              newLabel: '高级搜索面板（多字段/短语/时间刷选）',
              classicLabel: '单框简单搜索',
              mode: 'new',
              chosenMode: null,
              effectiveMode: 'new',
              expired: false,
              expiresAt: null,
              compatDays: 90,
              setAt: null,
            },
          ],
          note: '回退只在明确并存的新旧交互间；旧实现按兼容期限保留，到期自动回到新交互。',
        }),
    )
    mockRoute(
      (url, init) =>
        url === '/api/v1/interaction-modes/search_advanced' && init?.method === 'PUT',
      () =>
        jsonResponse({
          key: 'search_advanced', mode: 'classic', effectiveMode: 'classic',
          expired: false, expiresAt: '2026-12-29T00:00:00+00:00', compatDays: 90,
          chosenMode: 'classic', setAt: 'TP', label: '搜索交互',
          newLabel: '新', classicLabel: '旧',
        }),
    )
    renderWithQuery(<InteractionModePrefsPanel />)
    expect(await screen.findByText(/高级搜索面板（多字段\/短语\/时间刷选）$/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '暂用旧交互' }))
    await waitFor(() => {
      const put = calls.find(
        (call) => call.url === '/api/v1/interaction-modes/search_advanced',
      )
      expect(put).toBeDefined()
      expect(JSON.parse(String(put!.init?.body))).toEqual({ mode: 'classic' })
    })
  })

  it('过期限的旧偏好如实标注并显示已回到新交互', async () => {
    mockRoute(
      (url) => url === '/api/v1/interaction-modes',
      () =>
        jsonResponse({
          surfaces: [
            {
              key: 'search_advanced',
              label: '搜索交互',
              newLabel: '高级搜索面板',
              classicLabel: '单框简单搜索',
              mode: 'new',
              chosenMode: 'classic',
              effectiveMode: 'new',
              expired: true,
              expiresAt: '2026-09-01T00:00:00+00:00',
              compatDays: 90,
              setAt: 'TP',
            },
          ],
          note: '',
        }),
    )
    renderWithQuery(<InteractionModePrefsPanel />)
    expect(
      await screen.findByText(/旧交互偏好已过兼容期限，自动回到新交互/),
    ).toBeInTheDocument()
    expect(screen.getByText('当前生效：新交互')).toBeInTheDocument()
  })
})
