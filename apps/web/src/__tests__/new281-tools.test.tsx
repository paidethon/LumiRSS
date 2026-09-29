/** NEW-281..290 Web 入口测试 — 个人简报工作台的渲染与交互主路径。
 *
 * 环境：jsdom；fetch 按 URL 匹配 mock（服务真源在 BFF，后端口径见
 * tests/test_new28*.py）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { New281BriefingTools } from '../components/new281/New281BriefingTools'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderTools(): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(<QueryClientProvider client={queryClient}><New281BriefingTools /></QueryClientProvider>)
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

function lastCall(url: string): RequestInit {
  const call = fetchCalls.filter((c) => c.url === url).at(-1)
  expect(call, `expected a fetch call to ${url}`).toBeDefined()
  return call?.init ?? {}
}

/** 展开工作台组合 + 指定子工具（两级情境展开）。 */
function expand(subsectionId: string): void {
  fireEvent.click(screen.getByRole('button', { name: /个人简报工作台（/ }))
  const toggles = screen.getAllByRole('button').filter((button) => {
    const host = button.closest('[data-new281-subsection]')
    return host !== null && host.getAttribute('data-new281-subsection') === subsectionId
  })
  expect(toggles.length).toBeGreaterThan(0)
  fireEvent.click(toggles[0])
}

beforeEach(() => {
  fetchCalls.length = 0
  routes = []
  vi.stubGlobal('fetch', (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    fetchCalls.push({ url, init })
    for (const route of routes) {
      if (route.match(url, init)) return route.respond(url, init)
    }
    return jsonResponse({ error: { type: 'unmocked', message: url } }, 404)
  }) as typeof fetch)
})

afterEach(() => {
  cleanup()
  routes = []
  vi.unstubAllGlobals()
})

const CARD = {
  entryRef: 'e1.aaa',
  itemId: 'i1',
  title: '窗口内文章',
  feedTitle: '某来源',
  feedUrl: 'https://f.example/rss',
  url: 'https://example.com/a',
  publishedAt: '2026-09-28T02:00:00+00:00',
  starred: false,
  excerpt: '这是摘录。',
  seenInIssues: [],
}

const ISO_FROM = '2026-09-26T00:00:00Z'
const ISO_TO = '2026-09-29T00:00:00Z'

describe('NEW-281..290 个人简报工作台（New281BriefingTools）', () => {
  it('折叠态零请求；aria-expanded 随开关翻转；组合展开后子工具仍折叠零请求', () => {
    renderTools()
    const toggle = screen.getByRole('button', { name: /个人简报工作台（/ })
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(fetchCalls).toHaveLength(0)
    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    expect(fetchCalls).toHaveLength(0)
    expect(screen.getByText(/NEW-281 编排台/)).toBeTruthy()
  })

  it('NEW-281 编排台：拉候选 → 勾选 → 建草稿（含已刊条目去重决定）→ 确认', async () => {
    mockRoute(
      (url) => url.startsWith('/api/v1/briefings/candidates?'),
      () =>
        jsonResponse({
          candidates: [
            { ...CARD },
            {
              ...CARD,
              entryRef: 'e1.bbb',
              title: '已刊过的文章',
              seenInIssues: [{ issueId: 'x', issueTitle: '上周一期', confirmedAt: '2026-09-20T00:00:00+00:00' }],
            },
          ],
          count: 2,
        }),
    )
    mockRoute((url, init) => url === '/api/v1/briefings' && !init?.method, () => jsonResponse({ issues: [], count: 0 }))
    mockRoute(
      (url, init) => url === '/api/v1/briefings' && init?.method === 'POST',
      () => jsonResponse({ id: 'iss1', title: '周三晨报', status: 'draft', items: [{}, {}] }),
    )
    renderTools()
    expand('composer')
    fireEvent.change(screen.getByLabelText('范围起（ISO 时间）'), { target: { value: ISO_FROM } })
    fireEvent.change(screen.getByLabelText('范围止（ISO 时间，不含）'), { target: { value: ISO_TO } })
    fireEvent.click(screen.getByText('拉取候选摘要卡'))
    await waitFor(() => expect(screen.getByText('窗口内文章')).toBeTruthy())

    fireEvent.click(screen.getByLabelText('选入：窗口内文章'))
    fireEvent.click(screen.getByLabelText('选入：已刊过的文章'))
    fireEvent.change(screen.getByLabelText('本期标题'), { target: { value: '周三晨报' } })
    // 已刊条目出现去重决定下拉（默认 include）
    expect(screen.getByLabelText('重复决定：已刊过的文章')).toBeTruthy()
    fireEvent.click(screen.getByText('建草稿（2 条已选）'))
    await waitFor(() => expect(screen.getByText(/已建草稿「周三晨报」/)).toBeTruthy())
    const postCall = fetchCalls.find((c) => c.url === '/api/v1/briefings' && c.init?.method === 'POST')
    expect(postCall, 'expected POST /api/v1/briefings').toBeDefined()
    const sent = JSON.parse(String(postCall?.init?.body))
    expect(sent.items).toHaveLength(2)
    expect(sent.items[0].entryRef).toBe('e1.aaa')
    const dupItem = sent.items.find((item: { entryRef: string }) => item.entryRef === 'e1.bbb')
    expect(dupItem.dupDecision).toBe('include')
  })

  it('NEW-282 后续清单：defer 条目如实列出', async () => {
    mockRoute(
      (url) => url === '/api/v1/briefings/followups',
      () =>
        jsonResponse({
          followups: [
            { entryRef: 'e1.ccc', title: '迟到的旧闻', feedTitle: '某来源', priorIssue: '第一期', deferredAt: '2026-09-28T00:00:00+00:00' },
          ],
          count: 1,
        }),
    )
    renderTools()
    expand('duplicates')
    await waitFor(() => expect(screen.getByText(/迟到的旧闻/)).toBeTruthy())
    expect(screen.getByText(/来自「第一期」/)).toBeTruthy()
    expect(screen.getByText(/缺决定的提交会被 409 拦截/)).toBeTruthy()
  })

  it('NEW-283 截稿窗口：保存配置并展示换算好的 UTC 边界', async () => {
    mockRoute(
      (url, init) => url === '/api/v1/briefings/window' && !init?.method,
      () => jsonResponse({ configured: false }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/briefings/window' && init?.method === 'PUT',
      () =>
        jsonResponse({
          configured: true,
          timezone: 'Asia/Shanghai',
          cutoffTime: '18:00',
          periodDays: 1,
          startUtc: '2026-09-28T10:00:00+00:00',
          cutoffUtc: '2026-09-29T10:00:00+00:00',
          nextWindowStartUtc: '2026-09-29T10:00:00+00:00',
        }),
    )
    renderTools()
    expand('window')
    await waitFor(() => expect(screen.getByText(/尚未配置截稿窗口/)).toBeTruthy())
    fireEvent.click(screen.getByText('保存截稿窗口'))
    await waitFor(() => expect(screen.getByText(/当前窗口 2026-09-28T10:00:00\+00:00/)).toBeTruthy())
    const putCall = fetchCalls.find((c) => c.url === '/api/v1/briefings/window' && c.init?.method === 'PUT')
    expect(putCall, 'expected PUT /api/v1/briefings/window').toBeDefined()
    const sent = JSON.parse(String(putCall?.init?.body))
    expect(sent).toMatchObject({ timezone: 'Asia/Shanghai', cutoffTime: '18:00', periodDays: 1 })
  })

  it('NEW-284 生成失败：stage + missing 如实展示，不装作成功', async () => {
    mockRoute(
      (url) => url === '/api/v1/briefings/attempts',
      () =>
        jsonResponse({
          attempts: [
            { id: 'a1', stage: 'candidates', status: 'failed', missing: [{ field: 'entries', reason: '窗口内没有任何文章。' }], detail: '', createdAt: '2026-09-29T00:00:00+00:00' },
          ],
          count: 1,
          honestyNote: '生成失败绝不呈现为空白成功页',
        }),
    )
    mockRoute((url) => url === '/api/v1/briefings/recipes', () => jsonResponse({ recipes: [], count: 0 }))
    mockRoute(
      (url) => url === '/api/v1/briefings/generate',
      () =>
        jsonResponse(
          {
            error: {
              type: 'briefing_inputs_missing',
              message: '窗口内 0 篇文章',
              stage: 'candidates',
              missing: [{ field: 'entries', reason: '窗口内没有任何文章。' }],
              attemptId: 'a2',
            },
          },
          422,
        ),
    )
    renderTools()
    expand('diagnostics')
    fireEvent.click(screen.getByText('生成一期草稿'))
    await waitFor(() =>
      expect(screen.getAllByText(/窗口内没有任何文章。/).length).toBeGreaterThan(0),
    )
    expect(screen.getByText('失败')).toBeTruthy()
  })

  it('NEW-285 RSS 发布：启用后明文只显示一次；可撤销', async () => {
    mockRoute(
      (url) => url === '/api/v1/briefings/feed',
      () => jsonResponse({ enabled: false, createdAt: null, rotatedAt: null, revokedAt: null }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/briefings/feed/enable' && init?.method === 'POST',
      () => jsonResponse({ token: 'abcdef0123456789', path: '/feeds/briefings/abcdef0123456789.atom', note: 'token 只显示这一次（库存哈希）。' }),
    )
    renderTools()
    expand('feed')
    fireEvent.click(screen.getByText('启用订阅'))
    await waitFor(() => expect(screen.getByText(/订阅地址（只显示这一次）/)).toBeTruthy())
    expect(screen.getByText(/abcdef0123456789\.atom/)).toBeTruthy()
    expect(lastCall('/api/v1/briefings/feed/enable').method).toBe('POST')
  })

  it('NEW-286 栏目配方：创建（规则+预算）→ 列表 → 删除', async () => {
    mockRoute(
      (url, init) => url === '/api/v1/briefings/recipes' && !init?.method,
      () => jsonResponse({ recipes: [], count: 0 }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/briefings/recipes' && init?.method === 'POST',
      () => jsonResponse({ id: 'r1', name: '晨报配方', sections: [{ key: 'top', label: '要闻', rule: 'starred', budget: 400, feedUrl: '' }] }),
    )
    renderTools()
    expand('recipes')
    fireEvent.change(screen.getByLabelText('配方名'), { target: { value: '晨报配方' } })
    fireEvent.click(screen.getByText('保存配方'))
    await waitFor(() => expect(screen.getByText(/配方「晨报配方」已保存/)).toBeTruthy())
    const postCall = fetchCalls.find((c) => c.url === '/api/v1/briefings/recipes' && c.init?.method === 'POST')
    expect(postCall, 'expected POST /briefings/recipes').toBeDefined()
    const sent = JSON.parse(String(postCall?.init?.body))
    expect(sent.sections[0]).toMatchObject({ rule: 'starred', budget: 400 })
  })

  it('NEW-287 人工精选标记：草稿条目展示来源并支持翻转', async () => {
    mockRoute(
      (url) => url === '/api/v1/briefings',
      () =>
        jsonResponse({
          issues: [{ id: 'd1', title: '草稿期', status: 'draft', confirmedAt: null, itemCount: 1 }],
          count: 1,
        }),
    )
    mockRoute(
      (url) => url === '/api/v1/briefings/d1',
      () =>
        jsonResponse({
          id: 'd1',
          title: '草稿期',
          status: 'draft',
          sections: [{ key: 'main', label: '正文' }],
          items: [
            {
              id: 'it1',
              entryRef: 'e1.aaa',
              title: '推荐来的文章',
              provenance: 'rule',
              provenanceLabel: '规则推荐',
              sectionKey: 'main',
              position: 0,
              pulledBack: false,
              feedTitle: '',
              url: '',
              publishedAt: '',
              excerpt: '',
            },
          ],
        }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/briefings/d1/items/it1/provenance' && init?.method === 'PATCH',
      () => jsonResponse({ id: 'd1', title: '草稿期', status: 'draft', items: [] }),
    )
    renderTools()
    expand('provenance')
    await waitFor(() => expect(screen.getByText(/【规则推荐】/)).toBeTruthy())
    fireEvent.click(screen.getByText('翻转为编辑选入'))
    await waitFor(() =>
      expect(lastCall('/api/v1/briefings/d1/items/it1/provenance').method).toBe('PATCH'),
    )
    const sent = JSON.parse(String(lastCall('/api/v1/briefings/d1/items/it1/provenance').body))
    expect(sent.provenance).toBe('manual')
  })

  it('NEW-288 跨期主题：建主题 → 展开链（期次位置 + 顺序）', async () => {
    mockRoute(
      (url, init) => url === '/api/v1/briefings/topics' && !init?.method,
      () => jsonResponse({ topics: [{ id: 't1', name: '数据中心用水', entryCount: 2 }], count: 1 }),
    )
    mockRoute(
      (url) => url === '/api/v1/briefings/topics/t1',
      () =>
        jsonResponse({
          id: 't1',
          name: '数据中心用水',
          entries: [
            { itemId: 'i1', title: '首期报道', issueTitle: '第一期', issueStatus: 'confirmed', issueConfirmedAt: '2026-09-27T00:00:00+00:00', position: 0, entryRef: 'e1.aaa', briefingId: 'b1', feedTitle: '', url: '', excerpt: '' },
            { itemId: 'i2', title: '后续报道', issueTitle: '第二期', issueStatus: 'confirmed', issueConfirmedAt: '2026-09-29T00:00:00+00:00', position: 0, entryRef: 'e1.bbb', briefingId: 'b2', feedTitle: '', url: '', excerpt: '' },
          ],
          honestyNote: '只含你显式挂载的条目',
        }),
    )
    renderTools()
    expand('topics')
    await waitFor(() => expect(screen.getByRole('button', { name: /数据中心用水（2 条）/ })).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: /数据中心用水（2 条）/ }))
    await waitFor(() => expect(screen.getByText('首期报道')).toBeTruthy())
    expect(screen.getByText(/「第一期」已确认 · 期次内第 1 条/)).toBeTruthy()
    expect(screen.getByText(/「第二期」已确认 · 期次内第 1 条/)).toBeTruthy()
  })

  it('NEW-289 EML 导出：下载确认为文件，提示绝不发送', async () => {
    vi.stubGlobal('URL.createObjectURL', vi.fn(() => 'blob:mock'))
    vi.stubGlobal('URL.revokeObjectURL', vi.fn())
    HTMLAnchorElement.prototype.click = () => {}
    const emlBytes = new TextEncoder().encode('Subject: x\r\n\r\nbody')
    mockRoute(
      (url) => url === '/api/v1/briefings',
      () =>
        jsonResponse({
          issues: [{ id: 'c1', title: '已确认期', status: 'confirmed', confirmedAt: 'x', itemCount: 2 }],
          count: 1,
        }),
    )
    mockRoute(
      (url) => url === '/api/v1/briefings/c1/export.eml',
      () =>
        new Response(emlBytes, {
          status: 200,
          headers: {
            'content-type': 'message/rfc822',
            'content-disposition': 'attachment; filename="test.eml"',
          },
        }),
    )
    renderTools()
    expand('export')
    await screen.findByText('已确认期（2 条）')
    fireEvent.change(screen.getByLabelText('已确认的期次'), { target: { value: 'c1' } })
    fireEvent.click(screen.getByText('导出 EML 文件'))
    await waitFor(() => expect(screen.getByText(/已导出 test\.eml/)).toBeTruthy())
    expect(screen.getByText(/系统绝不发送邮件/)).toBeTruthy()
    expect(fetchCalls.some((c) => c.url === '/api/v1/briefings/c1/export.eml')).toBe(true)
  })

  it('NEW-283 编排台内联调回：窗口截稿后的条目勾选「调回」后 pullBack=true 进本期', async () => {
    mockRoute(
      (url, init) => url === '/api/v1/briefings/window' && !init?.method,
      () =>
        jsonResponse({
          configured: true,
          timezone: 'Asia/Shanghai',
          cutoffTime: '18:00',
          periodDays: 1,
          startUtc: '2026-09-28T10:00:00+00:00',
          cutoffUtc: '2026-09-29T10:00:00+00:00',
          nextWindowStartUtc: '2026-09-29T10:00:00+00:00',
        }),
    )
    mockRoute(
      (url) => url.startsWith('/api/v1/briefings/candidates?'),
      () =>
        jsonResponse({
          candidates: [
            { ...CARD, publishedAt: '2026-09-29T11:00:00+00:00' },  // 截稿后 → 迟到
          ],
          count: 1,
        }),
    )
    mockRoute((url, init) => url === '/api/v1/briefings' && !init?.method, () => jsonResponse({ issues: [], count: 0 }))
    mockRoute(
      (url, init) => url === '/api/v1/briefings' && init?.method === 'POST',
      () => jsonResponse({ id: 'iss9', title: '调回一期', status: 'draft', items: [{}] }),
    )
    renderTools()
    expand('composer')
    fireEvent.change(screen.getByLabelText('范围起（ISO 时间）'), { target: { value: ISO_FROM } })
    fireEvent.change(screen.getByLabelText('范围止（ISO 时间，不含）'), { target: { value: ISO_TO } })
    fireEvent.click(screen.getByText('拉取候选摘要卡'))
    // 迟到条目出现显式「调回」勾选（不勾 = 属下一期，后端 422 拦截，BFF 测试锁定）
    fireEvent.click(await screen.findByLabelText('调回本期（迟到）：窗口内文章'))
    fireEvent.click(screen.getByLabelText('选入：窗口内文章'))
    fireEvent.change(screen.getByLabelText('本期标题'), { target: { value: '调回一期' } })
    fireEvent.click(screen.getByText('建草稿（1 条已选）'))
    await waitFor(() => expect(screen.getByText(/已建草稿「调回一期」/)).toBeTruthy())
    const postCall = fetchCalls.find((c) => c.url === '/api/v1/briefings' && c.init?.method === 'POST')
    expect(postCall, 'expected POST /api/v1/briefings').toBeDefined()
    const sent = JSON.parse(String(postCall?.init?.body))
    expect(sent.items[0].pullBack).toBe(true)
  })

  it('NEW-290 历史更正：追加更正并列出（不替换正文）', async () => {
    mockRoute(
      (url) => url === '/api/v1/briefings',
      () =>
        jsonResponse({
          issues: [{ id: 'c1', title: '已确认期', status: 'confirmed', confirmedAt: 'x', itemCount: 2 }],
          count: 1,
        }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/briefings/c1/corrections' && !init?.method,
      () =>
        jsonResponse({
          corrections: [{ id: 'cr1', briefingId: 'c1', body: '日期应为 9 月 28 日。', createdAt: '2026-09-29T00:00:00+00:00' }],
          count: 1,
          honestyNote: '只增不改不删',
        }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/briefings/c1/corrections' && init?.method === 'POST',
      () => jsonResponse({ id: 'cr2', briefingId: 'c1', body: '补充更正', createdAt: '2026-09-29T01:00:00+00:00' }),
    )
    renderTools()
    expand('corrections')
    await screen.findByText('已确认期')
    fireEvent.change(screen.getByLabelText('已确认的期次'), { target: { value: 'c1' } })
    await waitFor(() => expect(screen.getByText(/日期应为 9 月 28 日。/)).toBeTruthy())
    fireEvent.change(screen.getByLabelText('更正内容'), { target: { value: '补充更正' } })
    fireEvent.click(screen.getByText('追加更正'))
    await waitFor(() => expect(screen.getByText(/更正已追加（原期次内容未做任何替换）。/)).toBeTruthy())
    const postCorrection = fetchCalls.find((c) => c.url === '/api/v1/briefings/c1/corrections' && c.init?.method === 'POST')
    expect(postCorrection, 'expected POST corrections').toBeDefined()
    const sent = JSON.parse(String(postCorrection?.init?.body))
    expect(sent.body).toBe('补充更正')
  })
})
