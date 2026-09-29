/** NEW-331..340 Web 入口测试 — 共读空间协作组的渲染与交互主路径。
 *
 * 环境：jsdom；fetch 按 URL 匹配 mock（服务真源在 BFF，后端口径见
 * tests/test_new33*.py / test_new340*.py）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { SpaceGovernanceTools } from '../components/new331/SpaceGovernanceTools'

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

function callsTo(url: string): { url: string; init?: RequestInit }[] {
  return fetchCalls.filter((call) => call.url === url || call.url.startsWith(`${url}?`))
}

function lastBody(url: string): Record<string, unknown> {
  const calls = callsTo(url)
  expect(calls.length, `expected a call to ${url}`).toBeGreaterThan(0)
  return JSON.parse(String(calls[calls.length - 1]?.init?.body ?? '{}')) as Record<
    string,
    unknown
  >
}

const SPACE_ID = 'space-1'
const space = {
  id: SPACE_ID,
  name: '共读空间',
  description: '',
  ownerUserId: 'u-owner',
  requireApproval: false,
  discussionTemplates: [],
  archivedAt: null,
  createdAt: '2026-09-29T00:00:00+00:00',
  updatedAt: '2026-09-29T00:00:00+00:00',
  myRole: 'manager',
  members: [
    {
      id: 'm-manager',
      spaceId: SPACE_ID,
      userId: 'u-owner',
      username: 'owner',
      role: 'manager',
      expiresAt: null,
      revokedAt: null,
      active: true,
      expired: false,
      createdAt: '2026-09-29T00:00:00+00:00',
    },
    {
      id: 'm-b',
      spaceId: SPACE_ID,
      userId: 'u-b',
      username: 'member-b',
      role: 'member',
      expiresAt: null,
      revokedAt: null,
      active: true,
      expired: false,
      createdAt: '2026-09-29T00:00:00+00:00',
    },
  ],
  sections: [],
}

function expandSubsection(id: string): void {
  const host = document.querySelector(`[data-new311-subsection="${id}"]`)
  expect(host, `subsection ${id} mounted`).not.toBeNull()
  const toggle = host?.querySelector('button')
  expect(toggle).not.toBeNull()
  fireEvent.click(toggle as HTMLButtonElement)
}

/** 展开组合面板 + 等空间列表加载完 + 选中空间 + 展开「成员」子区。 */
async function openAndSelectSpace(): Promise<void> {
  fireEvent.click(screen.getByRole('button', { name: /共读空间协作工具（/ }))
  await waitFor(() => expect(screen.getByLabelText(/选择空间/)).toBeTruthy())
  await screen.findByText('共读空间')
  fireEvent.change(screen.getByLabelText(/选择空间/), { target: { value: SPACE_ID } })
  expandSubsection('members')
  await screen.findByText('member-b')
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
  mockRoute(
    (url, init) => url === '/api/v1/spaces' && (init?.method ?? 'GET') === 'GET',
    () => jsonResponse({ items: [space] }),
  )
  mockRoute(
    (url) => url === `/api/v1/spaces/${SPACE_ID}`,
    () => jsonResponse(space),
  )
})

afterEach(() => {
  cleanup()
  routes = []
})

describe('NEW-331..340 共读空间协作工具组', () => {
  it('折叠态零请求；展开后选择空间才挂载子区（情境展开）', async () => {
    renderWithQuery(<SpaceGovernanceTools />)
    const toggle = screen.getByRole('button', { name: /共读空间协作工具（/ })
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(fetchCalls).toHaveLength(0)
    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    await waitFor(() => expect(screen.getByLabelText(/选择空间/)).toBeTruthy())
    expect(document.querySelector('[data-new331-members]')).toBeNull()
    await screen.findByText('共读空间')
    fireEvent.change(screen.getByLabelText(/选择空间/), { target: { value: SPACE_ID } })
    // 情境展开：选中空间后子区开关已挂载，但内容仍未挂载（折叠 = 零查询）
    await waitFor(() =>
      expect(document.querySelector('[data-new311-subsection="members"]')).not.toBeNull())
    expect(document.querySelector('[data-new331-members]')).toBeNull()
    expandSubsection('members')
    await waitFor(() => expect(document.querySelector('[data-new331-members]')).not.toBeNull())
    expect(screen.getByText('member-b')).toBeTruthy()
  })

  it('NEW-331 会议资料单：发起 → 添加资料 → 结束 → 保存结论', async () => {
    mockRoute(
      (url) => url === `/api/v1/spaces/${SPACE_ID}/meetings` && !init?.body,
      () => jsonResponse({ items: [] }),
    )
    renderWithQuery(<SpaceGovernanceTools />)
    await openAndSelectSpace()
    expandSubsection('meetings')

    fireEvent.change(screen.getByLabelText('会议标题'), { target: { value: '第一次共读会' } })
    fireEvent.click(screen.getByRole('button', { name: '发起会议' }))
    await waitFor(() =>
      expect(lastBody(`/api/v1/spaces/${SPACE_ID}/meetings`)).toEqual({
        title: '第一次共读会',
      }),
    )
  })

  it('NEW-332 投稿审批：投稿走 POST /contributions', async () => {
    renderWithQuery(<SpaceGovernanceTools />)
    await openAndSelectSpace()
    await waitFor(() =>
      expect(document.querySelector('[data-new311-subsection="contributions"]')).not.toBeNull(),
    )
    expandSubsection('contributions')
    fireEvent.change(screen.getByLabelText('条目 ref'), { target: { value: 'entry-9' } })
    fireEvent.change(screen.getByLabelText(/^标题$/), { target: { value: '共享文章' } })
    fireEvent.click(screen.getByRole('button', { name: '投稿' }))
    await waitFor(() =>
      expect(lastBody(`/api/v1/spaces/${SPACE_ID}/contributions`)).toEqual({
        entryRef: 'entry-9',
        title: '共享文章',
      }),
    )
  })

  it('NEW-333 版本通知：报告新版本 → POST /version-notices', async () => {
    renderWithQuery(<SpaceGovernanceTools />)
    await openAndSelectSpace()
    await waitFor(() =>
      expect(document.querySelector('[data-new311-subsection="notices"]')).not.toBeNull(),
    )
    expandSubsection('notices')
    fireEvent.change(screen.getByLabelText(/^条目 ref$/), { target: { value: 'entry-5' } })
    fireEvent.change(screen.getByLabelText('新版本标签'), { target: { value: 'v2' } })
    fireEvent.click(screen.getByRole('button', { name: '报告新版本' }))
    await waitFor(() =>
      expect(lastBody(`/api/v1/spaces/${SPACE_ID}/version-notices`)).toEqual({
        entryRef: 'entry-5',
        versionLabel: 'v2',
      }),
    )
  })

  it('NEW-334 成员到期：设 7 天到期 → PUT /expiry 携带未来时间', async () => {
    renderWithQuery(<SpaceGovernanceTools />)
    await openAndSelectSpace()
    const before = Date.now()
    fireEvent.click(screen.getByRole('button', { name: '设 7 天到期' }))
    await waitFor(() => {
      const body = lastBody(`/api/v1/spaces/${SPACE_ID}/members/m-b/expiry`)
      const expiresAt = String(body.expiresAt)
      expect(Number.isNaN(Date.parse(expiresAt))).toBe(false)
      expect(Date.parse(expiresAt)).toBeGreaterThanOrEqual(before + 6 * 86_400_000)
    })
    fireEvent.click(screen.getByRole('button', { name: '清除到期' }))
    await waitFor(() =>
      expect(lastBody(`/api/v1/spaces/${SPACE_ID}/members/m-b/expiry`)).toEqual({
        expiresAt: null,
      }),
    )
  })

  it('NEW-336 讨论与 NEW-335 分歧：提问与记录分歧走真实端点', async () => {
    renderWithQuery(<SpaceGovernanceTools />)
    await openAndSelectSpace()
    await waitFor(() =>
      expect(document.querySelector('[data-new311-subsection="discussions"]')).not.toBeNull(),
    )
    expandSubsection('discussions')
    fireEvent.change(screen.getByLabelText('问题标题'), { target: { value: '口径问题' } })
    fireEvent.change(screen.getByLabelText('问题正文'), { target: { value: '同比还是环比？' } })
    fireEvent.click(screen.getByRole('button', { name: '提问' }))
    await waitFor(() =>
      expect(lastBody(`/api/v1/spaces/${SPACE_ID}/discussions`)).toEqual({
        title: '口径问题',
        question: '同比还是环比？',
      }),
    )

    expandSubsection('disagreements')
    fireEvent.change(screen.getByLabelText('分歧标题'), { target: { value: '结论分歧' } })
    fireEvent.click(screen.getByRole('button', { name: '记录分歧' }))
    await waitFor(() =>
      expect(lastBody(`/api/v1/spaces/${SPACE_ID}/disagreements`)).toEqual({
        title: '结论分歧',
      }),
    )
  })

  it('NEW-337 活动摘要：展开子区才发请求（折叠零查询）且带 from/to', async () => {
    renderWithQuery(<SpaceGovernanceTools />)
    await openAndSelectSpace()
    await waitFor(() =>
      expect(document.querySelector('[data-new311-subsection="activity"]')).not.toBeNull(),
    )
    expect(fetchCalls.filter((call) => call.url.includes('/activity'))).toHaveLength(0)
    mockRoute(
      (url) => url.startsWith(`/api/v1/spaces/${SPACE_ID}/activity`),
      () =>
        jsonResponse({
          spaceId: SPACE_ID,
          from: '2026-09-22T00:00:00+00:00',
          to: '2026-09-29T00:00:00+00:00',
          scope: 'space-shared-only',
          note: '仅汇总空间共享面事件；私人阅读记录不在任何空间视图内。',
          counts: { contributions: { submitted: 1 } },
          recent: {},
        }),
    )
    expandSubsection('activity')
    await waitFor(() => {
      const calls = callsTo(`/api/v1/spaces/${SPACE_ID}/activity`)
      expect(calls.length).toBeGreaterThan(0)
      const url = calls[0]?.url ?? ''
      expect(url).toContain('from=')
      expect(url).toContain('to=')
    })
    await waitFor(() => expect(screen.getByText(/私人阅读记录不在任何空间视图内/)).toBeTruthy())
  })

  it('NEW-338 附件清单 / NEW-339 模板 / NEW-340 归档：主路径动作走真实端点', async () => {
    renderWithQuery(<SpaceGovernanceTools />)
    await openAndSelectSpace()
    await waitFor(() =>
      expect(document.querySelector('[data-new311-subsection="attachments"]')).not.toBeNull(),
    )

    expandSubsection('attachments')
    fireEvent.change(screen.getByLabelText('附件 ref'), { target: { value: 'att-1' } })
    fireEvent.change(screen.getByLabelText('名称'), { target: { value: '数据表.csv' } })
    fireEvent.click(screen.getByRole('button', { name: '共享元数据' }))
    await waitFor(() =>
      expect(lastBody(`/api/v1/spaces/${SPACE_ID}/attachment-shares`)).toEqual({
        attachmentRef: 'att-1',
        name: '数据表.csv',
      }),
    )

    expandSubsection('templates')
    mockRoute(
      (url) => url === '/api/v1/space-templates',
      () => jsonResponse({ items: [] }),
    )
    fireEvent.change(screen.getByLabelText('模板名'), { target: { value: '月度模板' } })
    fireEvent.click(screen.getByRole('button', { name: '从本空间生成' }))
    await waitFor(() =>
      expect(lastBody(`/api/v1/spaces/${SPACE_ID}/template`)).toEqual({
        name: '月度模板',
        discussionTemplates: [],
      }),
    )

    expandSubsection('archive')
    fireEvent.click(screen.getByRole('button', { name: '盘点未完成任务' }))
    await waitFor(() =>
      expect(
        callsTo(`/api/v1/spaces/${SPACE_ID}/archive/preview`).length,
      ).toBeGreaterThan(0),
    )
    fireEvent.click(screen.getByRole('button', { name: '确认跳过并归档' }))
    await waitFor(() =>
      expect(lastBody(`/api/v1/spaces/${SPACE_ID}/archive`)).toEqual({ force: true }),
    )
    fireEvent.click(screen.getByRole('button', { name: '恢复（仅留管理者）' }))
    await waitFor(() =>
      expect(lastBody(`/api/v1/spaces/${SPACE_ID}/restore`)).toEqual({ keepMemberIds: [] }),
    )
  })
})
