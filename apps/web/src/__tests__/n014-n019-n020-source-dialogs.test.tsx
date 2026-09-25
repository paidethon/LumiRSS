/** N014/N019/N020 UI — 低活跃建议面板、来源设置对话框（关注级别 +
 * 结构化接入说明卡）。
 *
 * - N014：建议行渲染依据（weeks/yield/medianGapDays）+ 诚实调度说明；
 *   接受建议 = POST apply（记录决定），已接受状态可见；
 * - N020：来源设置对话框的关注级别 select，保存载荷携带 attentionLevel；
 * - N019：接入说明卡编辑器保存 → PUT payload 只含四个结构化字段，
 *   凭据归属是标签（self/shared/none），界面上不存在凭据值输入。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FreshnessSuggestionsSection } from '../components/FreshnessSuggestionsSection'
import { SourcePolicyDialog } from '../components/subscription-w3-panels'

const FEED_URL = 'https://sparse.example/rss'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderWithRoutes(
  ui: React.ReactElement,
  routes: Record<string, () => Response>,
) {
  const calls: { method: string; url: string; body?: unknown }[] = []
  const fn = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    let body: unknown
    try {
      body = init?.body !== undefined ? JSON.parse(String(init.body)) : undefined
    } catch {
      body = init?.body
    }
    calls.push({ method, url, body })
    const handler = routes[`${method} ${url}`]
    if (handler === undefined) return Promise.resolve(jsonResponse({}))
    return Promise.resolve(handler())
  })
  vi.stubGlobal('fetch', fn)
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
  return { calls }
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

// ---- N014 低活跃建议面板 ------------------------------------------------------

const SUGGESTION = {
  items: [
    {
      feedUrl: FEED_URL,
      subscriptionRef: 's1.feed/11',
      title: 'Sparse 源',
      currentPattern: '默认',
      suggested: '降低刷新频率',
      basis: { weeks: 8, yield: 0.25, medianGapDays: 30.5 },
      refreshAdvisory: null,
    },
  ],
  schedulingNote: 'FreshRSS 的抓取调度粒度由实例 CRON_MIN 决定，greader API 不提供 per-feed 刷新频率。',
  basis: 'search_entries 派生投影（published_at，trailing 8 周）',
  generatedAt: '2026-09-25T00:00:00Z',
}

describe('N014 低活跃建议面板', () => {
  it('渲染建议依据 + 诚实调度说明；接受建议 → POST apply 记录决定', async () => {
    const { calls } = renderWithRoutes(<FreshnessSuggestionsSection />, {
      'GET /api/v1/sources/freshness-suggestions': () => jsonResponse(SUGGESTION),
      // P09 native-url 在未绑定部署上 409（面板降级隐藏链接）
      'GET /api/v1/freshrss/native-url': () => jsonResponse({}, 409),
      'POST /api/v1/sources/freshness-suggestions/apply': () =>
        jsonResponse({ feedUrl: FEED_URL, refreshAdvisory: 'accepted', schedulingNote: 'ok' }),
    })
    const item = await screen.findByTestId('freshness-suggestion-item')
    expect(item.textContent).toContain('Sparse 源')
    expect(item.textContent).toContain('8')
    expect(item.textContent).toContain('0.25')
    expect(item.textContent).toContain('30.5')
    expect(item.textContent).toContain('CRON_MIN')

    fireEvent.click(screen.getByRole('button', { name: '接受建议（记录决定）' }))
    // waitFor 依赖回调抛错重试（返回 falsy 不会继续等待）。
    await waitFor(() => {
      expect(
        calls.find((c) => c.method === 'POST' && c.url.includes('freshness-suggestions/apply')),
      ).toBeDefined()
    })
    const apply = calls.find((c) => c.method === 'POST' && c.url.includes('freshness-suggestions/apply'))
    expect(apply?.body).toEqual({ feedUrl: FEED_URL })
  })

  it('已接受低频建议 → 状态可见，不再重复出现接受按钮', async () => {
    renderWithRoutes(
      <FreshnessSuggestionsSection />,
      {
        'GET /api/v1/sources/freshness-suggestions': () =>
          jsonResponse({
            ...SUGGESTION,
            items: [{ ...SUGGESTION.items[0], refreshAdvisory: 'accepted' }],
          }),
        'GET /api/v1/freshrss/native-url': () => jsonResponse({}, 409),
      },
    )
    await screen.findByTestId('freshness-suggestion-item')
    expect(screen.getByTestId('advisory-accepted').textContent).toContain('已接受低频建议')
    expect(screen.queryByRole('button', { name: '接受建议（记录决定）' })).toBeNull()
  })

  it('无建议 → 诚实空态', async () => {
    renderWithRoutes(<FreshnessSuggestionsSection />, {
      'GET /api/v1/sources/freshness-suggestions': () => jsonResponse({ ...SUGGESTION, items: [] }),
      'GET /api/v1/freshrss/native-url': () => jsonResponse({}, 409),
    })
    await screen.findByText(/暂无低活跃建议/)
  })
})

// ---- N020 + N019 来源设置对话框 ------------------------------------------------

const OVERRIDES = {
  items: [
    {
      feedUrl: FEED_URL,
      hiddenUntil: null,
      showFrom: null,
      staleAlertHours: null,
      extractPolicy: 'rss',
      readerStyle: null,
      aiDisabled: false,
      muteWindows: null,
      attentionLevel: 'must_read',
      refreshAdvisory: 'accepted',
      updatedAt: '2026-09-25T00:00:00Z',
    },
  ],
}

function renderPolicyDialog(routes: Record<string, () => Response>) {
  return renderWithRoutes(
    <SourcePolicyDialog open onClose={() => {}} feedUrl={FEED_URL} title="Sparse 源" />,
    routes,
  )
}

describe('N020/N019 来源设置对话框', () => {
  it('N020: 关注级别 select 服务端值回显；保存载荷携带 attentionLevel', async () => {
    const { calls } = renderPolicyDialog({
      'GET /api/v1/sources/overrides': () => jsonResponse(OVERRIDES),
      [`GET /api/v1/sources/access-card?feedUrl=${encodeURIComponent(FEED_URL)}`]: () =>
        jsonResponse({ feedUrl: FEED_URL, acquisition: null, limits: null, credentialOwnership: null, maintenance: null, updatedAt: null }),
      'PUT /api/v1/sources/overrides': () => jsonResponse(OVERRIDES.items[0]),
    })
    const select = screen.getByTestId('attention-level-select') as HTMLSelectElement
    // 服务端值回显（waitFor 依赖回调抛错重试）。
    await waitFor(() => expect(select.value).toBe('must_read'))
    await screen.findByText(/继承状态：已覆盖/)
    fireEvent.change(select, { target: { value: 'low' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    // waitFor 依赖回调抛错重试（返回 falsy 不会继续等待）。
    await waitFor(() => {
      expect(calls.find((c) => c.method === 'PUT' && c.url.endsWith('/sources/overrides'))).toBeDefined()
    })
    const put = calls.find((c) => c.method === 'PUT' && c.url.endsWith('/sources/overrides'))
    expect((put?.body as Record<string, unknown>).attentionLevel).toBe('low')
    expect((put?.body as Record<string, unknown>).feedUrl).toBe(FEED_URL)
  })

  it('N014: 已接受低频建议在来源设置中如实呈现', async () => {
    renderPolicyDialog({
      'GET /api/v1/sources/overrides': () => jsonResponse(OVERRIDES),
      [`GET /api/v1/sources/access-card?feedUrl=${encodeURIComponent(FEED_URL)}`]: () =>
        jsonResponse({ feedUrl: FEED_URL, acquisition: null, limits: null, credentialOwnership: null, maintenance: null, updatedAt: null }),
    })
    await screen.findByTestId('refresh-advisory-accepted')
    expect(screen.getByTestId('refresh-advisory-accepted').textContent).toContain('CRON_MIN')
  })

  it('N019: 接入说明卡保存 → PUT 只含结构化字段；凭据归属是标签', async () => {
    const { calls } = renderPolicyDialog({
      'GET /api/v1/sources/overrides': () => jsonResponse({ items: [] }),
      [`GET /api/v1/sources/access-card?feedUrl=${encodeURIComponent(FEED_URL)}`]: () =>
        jsonResponse({ feedUrl: FEED_URL, acquisition: null, limits: null, credentialOwnership: null, maintenance: null, updatedAt: null }),
      'PUT /api/v1/sources/access-card': () =>
        jsonResponse({ feedUrl: FEED_URL, acquisition: 'RSSHub 路由', limits: null, credentialOwnership: 'shared', maintenance: null, updatedAt: 't' }),
    })
    const editor = await screen.findByTestId('access-card-editor')
    expect(editor).not.toBeNull()
    fireEvent.change(screen.getByRole('textbox', { name: '获取方式' }), {
      target: { value: 'RSSHub 路由' },
    })
    fireEvent.change(screen.getByLabelText('凭据归属'), { target: { value: 'shared' } })
    fireEvent.click(screen.getByRole('button', { name: '保存接入卡' }))
    // waitFor 依赖回调抛错重试（返回 falsy 不会继续等待）。
    await waitFor(() => {
      expect(calls.find((c) => c.method === 'PUT' && c.url.includes('/sources/access-card'))).toBeDefined()
    })
    const put = calls.find((c) => c.method === 'PUT' && c.url.includes('/sources/access-card'))
    const body = put?.body as Record<string, unknown>
    // 契约：只有四个结构化字段键，绝无凭据值字段。
    expect(Object.keys(body).sort()).toEqual(
      ['acquisition', 'credentialOwnership', 'feedUrl', 'limits', 'maintenance'].sort(),
    )
    expect(body.credentialOwnership).toBe('shared')
    // 界面不存在「凭据值」输入（只有归属标签下拉）。
    expect(screen.queryByRole('textbox', { name: '凭据值' })).toBeNull()
    await screen.findByTestId('access-card-saved')
  })
})
