/** NEW-241..250 Web 入口测试 — 原文版本与溯源工具组合的渲染与交互主路径。
 *
 * 环境：jsdom；fetch 按 URL 匹配 mock（服务真源在 BFF，后端口径见
 * tests/test_new24*.py / test_new250_*.py）。工具组合默认折叠（情境展开，
 * MASTER §6）：折叠态零请求由专项断言覆盖。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { New241SourceTools } from '../components/new241/New241SourceTools'

const ENTRY = 'e-1'

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
  render(<QueryClientProvider client={queryClient}><New241SourceTools entryRef={ENTRY} /></QueryClientProvider>)
}

const fetchCalls: { url: string; init?: RequestInit }[] = []
let routes: { match: (url: string, init?: RequestInit) => boolean; respond: (url: string, init?: RequestInit) => Response }[] = []

function mockRoute(
  matcher: (url: string, init?: RequestInit) => boolean,
  responder: (url: string, init?: RequestInit) => Response,
): void {
  routes.push({ match: matcher, respond: responder })
}

function get(url: string, body: unknown, status = 200): void {
  mockRoute((u) => u === url, () => jsonResponse(body, status))
}

/** 展开态下的公共 GET 面：每个测试自带，避免未 mock 路由 404 干扰。 */
function defaultReadRoutes(): void {
  get(`/api/v1/entries/${ENTRY}/article-versions`, { entryRef: ENTRY, items: [] })
  get(`/api/v1/entries/${ENTRY}/source-timeline`, {
    entryRef: ENTRY,
    projectionKnown: true,
    items: [
      { kind: 'published', label: '发表', time: 't0', available: true, source: 'feed 的 published 字段' },
      { kind: 'updated', label: '更新', time: null, available: false, source: '没有修订记录' },
    ],
  })
  get(`/api/v1/entries/${ENTRY}/source-timeline/annotations`, { items: [] })
  get(`/api/v1/entries/${ENTRY}/raw-fields`, {
    entryRef: ENTRY,
    fields: [
      { key: 'title', value: '原始标题', present: true, appMapping: '文章标题', sourceDescription: 'RSS <title>' },
    ],
  })
  get(`/api/v1/entries/${ENTRY}/raw-fields/reports`, { items: [] })
  get('/api/v1/library/link-recheck/results', { items: [] })
  get('/api/v1/citations', { items: [] })
  get('/api/v1/citation-edges', { items: [] })
  get(`/api/v1/entries/${ENTRY}/content-watch`, { error: { type: 'content_watch_not_found' } }, 404)
  get('/api/v1/links/detrack-kept-params', { items: [] })
}

beforeEach(() => {
  fetchCalls.length = 0
  routes = []
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    fetchCalls.push({ url, init })
    // 后注册的路由优先：测试可在 defaultReadRoutes 之后覆盖某个 GET
    for (let i = routes.length - 1; i >= 0; i -= 1) {
      if (routes[i].match(url, init)) return routes[i].respond(url, init)
    }
    return jsonResponse({ error: { type: 'unmocked', message: url } }, 404)
  }) as typeof fetch
})

afterEach(() => {
  cleanup()
  routes = []
})

async function expand(): Promise<void> {
  const toggle = await screen.findByRole('button', { name: /原文版本与溯源工具（/ })
  expect(toggle.getAttribute('aria-expanded')).toBe('false')
  fireEvent.click(toggle)
  expect(toggle.getAttribute('aria-expanded')).toBe('true')
}

describe('NEW-241..250 原文版本与溯源工具组', () => {
  it('默认折叠零请求；展开后才发起查询（情境展开）', async () => {
    defaultReadRoutes()
    renderTools()
    const toggle = screen.getByRole('button', { name: /原文版本与溯源工具（/ })
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(fetchCalls).toHaveLength(0)
    fireEvent.click(toggle)
    await screen.findByLabelText('文章更新差异阅读（NEW-241）')
    await waitFor(() =>
      expect(fetchCalls.some((c) => c.url === `/api/v1/entries/${ENTRY}/source-timeline`)).toBe(true),
    )
  })

  it('NEW-241 保存版本后对比段落差异', async () => {
    defaultReadRoutes()
    mockRoute(
      (url, init) => url === `/api/v1/entries/${ENTRY}/article-versions` && init?.method === 'POST',
      () => jsonResponse({ id: 'v-1', label: '初版', origin: 'user', createdAt: 't', contentChars: 5 }, 201),
    )
    get(`/api/v1/entries/${ENTRY}/article-versions`, {
      entryRef: ENTRY,
      items: [
        { id: 'v-1', label: '初版', origin: 'user', createdAt: 't', contentChars: 5 },
        { id: 'v-2', label: '二版', origin: 'user', createdAt: 't2', contentChars: 7 },
      ],
    })
    mockRoute(
      (url) => url.startsWith(`/api/v1/entries/${ENTRY}/article-versions/diff`),
      () =>
        jsonResponse({
          entryRef: ENTRY,
          fromVersion: 'v-1',
          toVersion: 'v-2',
          blocks: [{ type: 'added', text: '新增段落' }],
          added: 1,
          removed: 0,
          modified: 0,
          unchanged: 1,
          identical: false,
        }),
    )
    renderTools()
    await expand()
    fireEvent.change(await screen.findByLabelText('新版本标签'), { target: { value: '二版' } })
    fireEvent.change(screen.getByLabelText('粘贴当前正文以保存为版本'), { target: { value: '正文一\n\n正文二' } })
    fireEvent.click(screen.getByText('保存为版本'))
    await waitFor(() => expect(screen.getByText('已保存为新版本。')).toBeTruthy())
    fireEvent.change(await screen.findByLabelText('选择基准版本'), { target: { value: 'v-1' } })
    fireEvent.change(screen.getByLabelText('选择对比版本'), { target: { value: 'v-2' } })
    fireEvent.click(screen.getByText('对比段落差异'))
    await waitFor(() => expect(screen.getByText(/增加 1 段/)).toBeTruthy())
    expect(screen.getByText(/新增段落/)).toBeTruthy()
    const diffCall = fetchCalls.find((c) => c.url.includes('/article-versions/diff'))
    expect(diffCall?.url).toContain('fromVersion=v-1')
    expect(diffCall?.url).toContain('toVersion=v-2')
  })

  it('NEW-242 时间轴逐项说明出处；备注按类保存', async () => {
    defaultReadRoutes()
    mockRoute(
      (url, init) =>
        url === `/api/v1/entries/${ENTRY}/source-timeline/annotations/published` && init?.method === 'PUT',
      () => jsonResponse({ kind: 'published', note: '来自 atom:published' }),
    )
    renderTools()
    await expand()
    await screen.findByLabelText('来源时间轴（NEW-242）')
    await screen.findByText(/发表：t0/)
    expect(screen.getByText(/来源：feed 的 published 字段/)).toBeTruthy()
    expect(screen.getByText(/更新：不可用/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText('备注时间类型'), { target: { value: 'published' } })
    fireEvent.change(screen.getByLabelText('时间备注内容'), { target: { value: '来自 atom:published' } })
    fireEvent.click(screen.getByText('保存备注'))
    await waitFor(() => expect(screen.getByText('备注已保存。')).toBeTruthy())
    const call = fetchCalls.find((c) => c.url?.includes('/source-timeline/annotations/published'))
    expect(call?.init?.method).toBe('PUT')
    expect(JSON.parse(String(call?.init?.body))).toEqual({ note: '来自 atom:published' })
  })

  it('NEW-243 脱敏字段带映射说明；错误映射报告只追加', async () => {
    defaultReadRoutes()
    mockRoute(
      (url, init) => url === `/api/v1/entries/${ENTRY}/raw-fields/reports` && init?.method === 'POST',
      () => jsonResponse({ id: 'r-1' }, 201),
    )
    get(`/api/v1/entries/${ENTRY}/raw-fields/reports`, {
      items: [{ id: 'r-1', fieldKey: 'title', problem: '作者被写进标题', expected: '', createdAt: 't' }],
    })
    renderTools()
    await expand()
    await screen.findByLabelText('原始 feed 字段查看器（NEW-243）')
    await screen.findByText('title')
    expect(screen.getByText(/应用映射：文章标题/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText('报告字段名'), { target: { value: 'title' } })
    fireEvent.change(screen.getByLabelText('映射问题描述'), { target: { value: '作者被写进标题' } })
    fireEvent.click(screen.getByText('报告错误映射'))
    await waitFor(() => expect(screen.getByText(/只追加台账/)).toBeTruthy())
    expect(screen.getByText(/作者被写进标题/)).toBeTruthy()
  })

  it('NEW-244 批量复核四档结果；无法判断不冒充失效', async () => {
    defaultReadRoutes()
    mockRoute(
      (url, init) => url === '/api/v1/library/link-recheck' && init?.method === 'POST',
      () =>
        jsonResponse({
          items: [
            { id: 'c-1', ref: ENTRY, url: 'https://u.example/a', status: 'ok', httpStatus: 200, finalUrl: null, detail: '', checkedAt: 't' },
            { id: 'c-2', ref: 'e-2', url: 'https://u.example/b', status: 'redirect', httpStatus: 301, finalUrl: 'https://u.example/b2', detail: '', checkedAt: 't' },
            { id: 'c-3', ref: 'e-3', url: 'https://u.example/c', status: 'dead', httpStatus: 404, finalUrl: null, detail: '', checkedAt: 't' },
            { id: 'c-4', ref: 'e-4', url: null, status: 'unknown', httpStatus: null, finalUrl: null, detail: 'timeout', checkedAt: 't' },
          ],
          count: 4,
        }),
    )
    renderTools()
    await expand()
    expect(await screen.findByLabelText('资料引用列表（每行一个）')).toBeTruthy()
    expect((screen.getByLabelText('资料引用列表（每行一个）') as HTMLTextAreaElement).value).toBe(ENTRY)
    fireEvent.click(screen.getByText('开始复核'))
    await waitFor(() => expect(screen.getByText(/本轮检查完成：4 条/)).toBeTruthy())
    expect(screen.getByText(/正常（HTTP 200）/)).toBeTruthy()
    expect(screen.getByText(/重定向（HTTP 301）/)).toBeTruthy()
    expect(screen.getByText(/失效（HTTP 404）/)).toBeTruthy()
    expect(screen.getByText(/无法判断；timeout/)).toBeTruthy()
    const call = fetchCalls.find((c) => c.url === '/api/v1/library/link-recheck')
    expect(JSON.parse(String(call?.init?.body))).toEqual({ refs: [ENTRY] })
  })

  it('NEW-245 原始值与用户补充值区分展示；补充可撤销', async () => {
    defaultReadRoutes()
    get('/api/v1/citations', {
      items: [
        {
          citationRef: 'cite-1',
          title: '缺作者的引用',
          registeredAt: 't',
          author: { original: null, supplement: '补的作者', effective: '补的作者', origin: 'supplement' },
          date: { original: '2020-01-01', supplement: null, effective: '2020-01-01', origin: 'original' },
        },
      ],
    })
    mockRoute(
      (url, init) =>
        url.startsWith('/api/v1/citations/cite-1/supplements/') && init?.method === 'DELETE',
      () => new Response(null, { status: 204 }),
    )
    renderTools()
    await expand()
    await screen.findByLabelText('引文出处补全（NEW-245）')
    await screen.findByText(/原始（空）→ 用户补充「补的作者」/)
    expect(screen.getByText(/原始「2020-01-01」/)).toBeTruthy()
    fireEvent.change(await screen.findByLabelText('选择要补充的引用'), { target: { value: 'cite-1' } })
    fireEvent.click(screen.getByText('撤销补充'))
    await waitFor(() => expect(screen.getByText('补充已撤销，原始值不变。')).toBeTruthy())
    expect(
      fetchCalls.some((c) => c.url === '/api/v1/citations/cite-1/supplements/author' && c.init?.method === 'DELETE'),
    ).toBe(true)
  })

  it('NEW-246 显式边登记 + 追踪；中间缺失诚实标注', async () => {
    defaultReadRoutes()
    mockRoute(
      (url, init) => url === '/api/v1/citation-edges' && init?.method === 'POST',
      () => jsonResponse({ id: 'edge-1', fromRef: ENTRY, toRef: 'e-9', note: '', registeredAt: 't' }, 201),
    )
    mockRoute(
      (url) => url.startsWith('/api/v1/citation-chain?'),
      () =>
        jsonResponse({
          startRef: ENTRY,
          chain: [
            { ref: ENTRY, missingLink: false, edges: [] },
            { ref: 'e-9', missingLink: true, edges: [] },
          ],
          cycle: false,
          truncated: false,
        }),
    )
    renderTools()
    await expand()
    await screen.findByLabelText('资料来源链（NEW-246）')
    fireEvent.change(screen.getByLabelText('被引方 ref'), { target: { value: 'e-9' } })
    fireEvent.click(screen.getByText('登记引用关系'))
    await waitFor(() => expect(screen.getByText(/引用关系已登记/)).toBeTruthy())
    fireEvent.click(screen.getByText('追踪引用链'))
    await waitFor(() => expect(screen.getByText(/中间环节缺失/)).toBeTruthy())
    expect(screen.getByText(/1\. e-1/)).toBeTruthy()
    expect(screen.getByText(/2\. e-9/)).toBeTruthy()
  })

  it('NEW-247 建关注 → 显式比对检出变化 → 差异入口展开', async () => {
    defaultReadRoutes()
    let watching = false
    let checked = false
    const watchStatus = () => ({
      id: 'w-1',
      entryRef: ENTRY,
      baselineSha256: 'aa',
      baselineChars: 2,
      status: checked ? 'changed' : 'watching',
      changedAt: checked ? 't2' : null,
      lastCheckedAt: checked ? 't2' : null,
      checksCount: checked ? 1 : 0,
      createdAt: 't',
    })
    mockRoute(
      (url, init) => url === `/api/v1/entries/${ENTRY}/content-watch` && (!init?.method || init.method === 'GET'),
      () => (watching ? jsonResponse(watchStatus()) : jsonResponse({ error: { type: 'content_watch_not_found' } }, 404)),
    )
    mockRoute(
      (url, init) => url === `/api/v1/entries/${ENTRY}/content-watch` && init?.method === 'POST',
      () => {
        watching = true
        return jsonResponse(watchStatus(), 201)
      },
    )
    mockRoute(
      (url, init) => url === `/api/v1/entries/${ENTRY}/content-watch/check` && init?.method === 'POST',
      () => {
        checked = true
        return jsonResponse({ entryRef: ENTRY, status: 'changed', changed: true, checkedAt: 't2' })
      },
    )
    mockRoute(
      (url) => url === `/api/v1/entries/${ENTRY}/content-watch/diff`,
      () =>
        jsonResponse({
          changedAt: 't2',
          blocks: [{ type: 'modified', oldText: '旧句', newText: '新句' }],
          added: 0,
          removed: 0,
          modified: 1,
          unchanged: 0,
          identical: false,
        }),
    )
    renderTools()
    await expand()
    fireEvent.change(await screen.findByLabelText('基线正文'), { target: { value: '旧句' } })
    fireEvent.click(screen.getByText('开始关注'))
    await waitFor(() => expect(screen.getByText(/已开始关注/)).toBeTruthy())
    fireEvent.change(await screen.findByLabelText('当前正文（用于比对）'), { target: { value: '新句' } })
    fireEvent.click(screen.getByText('提交比对'))
    await waitFor(() => expect(screen.getByText('检测到正文变化。')).toBeTruthy())
    await waitFor(() => expect(screen.getByText(/修改 1 段/)).toBeTruthy())
    expect(screen.getByText(/旧句 → 新句/)).toBeTruthy()
  })

  it('NEW-248 预览区分移除与保留；必需参数不入移除清单', async () => {
    defaultReadRoutes()
    mockRoute(
      (url, init) => url === '/api/v1/links/detrack-preview' && init?.method === 'POST',
      () =>
        jsonResponse({
          supported: true,
          removed: ['utm_source'],
          keptRequired: ['sessionid'],
          keptUser: [],
          cleanedUrl: 'https://u.example/a',
          url: 'https://u.example/a?utm_source=x&sessionid=y',
        }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/links/detrack-kept-params/lang' && init?.method === 'PUT',
      () => jsonResponse({ param: 'lang', reason: '内容选择必需' }),
    )
    renderTools()
    await expand()
    fireEvent.change(await screen.findByLabelText('来源链接地址'), {
      target: { value: 'https://u.example/a?utm_source=x&sessionid=y' },
    })
    fireEvent.click(screen.getByText('预览去追踪'))
    await waitFor(() => expect(screen.getByLabelText('去追踪预览结果')).toBeTruthy())
    expect(screen.getByText(/将移除：utm_source/)).toBeTruthy()
    expect(screen.getByText(/sessionid/)).toBeTruthy()
    expect(screen.getByLabelText('去追踪后的链接')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('新保留参数名'), { target: { value: 'lang' } })
    fireEvent.change(screen.getByLabelText('保留理由'), { target: { value: '内容选择必需' } })
    fireEvent.click(screen.getByText('标记保留'))
    await waitFor(() => expect(screen.getByText(/已标记保留/)).toBeTruthy())
    expect(
      fetchCalls.some((c) => c.url === '/api/v1/links/detrack-kept-params/lang' && c.init?.method === 'PUT'),
    ).toBe(true)
  })

  it('NEW-249 许可证提示：未知明确标未知并附免责声明', async () => {
    defaultReadRoutes()
    mockRoute(
      (url, init) => url === '/api/v1/licenses/e-1' && init?.method === 'PUT',
      () =>
        jsonResponse({
          targetRef: 'e-1',
          status: 'recorded',
          licenseText: 'CC BY-SA 4.0',
          infoSource: 'user_record',
          note: '',
          updatedAt: 't',
        }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/licenses/notice-preview' && init?.method === 'POST',
      () =>
        jsonResponse({
          items: [
            { targetRef: 'e-1', status: 'recorded', licenseText: 'CC BY-SA 4.0', infoSource: 'user_record', note: '', updatedAt: 't' },
            { targetRef: 'e-ghost', status: 'unknown', licenseText: null, infoSource: null, note: '', updatedAt: null },
          ],
          unknownCount: 1,
          disclaimer: '仅转述记录与来源明示信息，不构成法律意见。',
        }),
    )
    renderTools()
    await expand()
    fireEvent.change(await screen.findByLabelText('许可证记录目标 ref'), { target: { value: 'e-1' } })
    fireEvent.change(screen.getByLabelText('许可证文本'), { target: { value: 'CC BY-SA 4.0' } })
    fireEvent.click(screen.getByText('保存许可证记录'))
    await waitFor(() => expect(screen.getByText('许可证记录已保存。')).toBeTruthy())
    fireEvent.change(screen.getByLabelText('汇编导出的资料 ref 列表（每行一个）'), {
      target: { value: 'e-1\ne-ghost' },
    })
    fireEvent.click(screen.getByText('预览引用限制提示'))
    await waitFor(() => expect(screen.getByLabelText('许可证提示预览')).toBeTruthy())
    expect(screen.getByText(/未知项 1 条/)).toBeTruthy()
    expect(screen.getByText(/不构成法律意见/)).toBeTruthy()
    expect(screen.getByText(/CC BY-SA 4.0/)).toBeTruthy()
  })

  it('NEW-250 检查单逐项列出缺项，补齐后计满', async () => {
    defaultReadRoutes()
    mockRoute(
      (url, init) => url === '/api/v1/evidence-checklists' && init?.method === 'POST',
      () => jsonResponse({ reportLabel: '九月综述', citationRefs: ['cite-1'] }, 201),
    )
    let patched = false
    const itemBase = {
      id: 'ev-1',
      citationRef: 'cite-1',
      sourceRef: null,
      versionId: null,
      excerpt: null,
      hasSource: false,
      hasVersion: false,
      versionExists: null,
      hasExcerpt: false,
      missing: ['source', 'version', 'excerpt'],
      complete: false,
      updatedAt: 't',
    }
    // 报告名含中文 → 实际请求 URL 为百分号编码，用 decodeURIComponent 匹配
    mockRoute(
      (url) => {
        try {
          return decodeURIComponent(url) === '/api/v1/evidence-checklists/九月综述'
        } catch {
          return false
        }
      },
      () =>
        jsonResponse({
          reportLabel: '九月综述',
          items: [
            patched
              ? { ...itemBase, sourceRef: 'e-1', hasSource: true, missing: ['version', 'excerpt'], complete: false }
              : itemBase,
          ],
          total: 1,
          completeCount: 0,
          missingCount: 1,
        }),
    )
    mockRoute(
      (url, init) => {
        if (init?.method !== 'PATCH') return false
        try {
          return decodeURIComponent(url) === '/api/v1/evidence-checklists/九月综述/items/cite-1'
        } catch {
          return false
        }
      },
      () => {
        patched = true
        return jsonResponse({ ...itemBase, sourceRef: 'e-1', hasSource: true, missing: ['version', 'excerpt'] })
      },
    )
    renderTools()
    await expand()
    fireEvent.change(await screen.findByLabelText('报告名称'), { target: { value: '九月综述' } })
    fireEvent.change(screen.getByLabelText('报告引文 ref 列表（每行一个）'), { target: { value: 'cite-1' } })
    fireEvent.click(screen.getByText('建立检查单'))
    await waitFor(() => expect(screen.getByText('检查单已建立。')).toBeTruthy())
    await waitFor(() => expect(screen.getByText(/完整 0 \/ 缺项 1/)).toBeTruthy())
    expect(screen.getByText(/缺：source、version、excerpt/)).toBeTruthy()
    fireEvent.change(await screen.findByLabelText('选择要补齐的引文项'), { target: { value: 'cite-1' } })
    fireEvent.change(screen.getByLabelText('补齐来源 ref'), { target: { value: 'e-1' } })
    fireEvent.click(screen.getByText('保存补齐'))
    await waitFor(() => expect(screen.getByText('缺项已补齐。')).toBeTruthy())
    const patchCall = fetchCalls.find((c) => c.url?.includes('/items/cite-1'))
    expect(patchCall?.init?.method).toBe('PATCH')
    expect(JSON.parse(String(patchCall?.init?.body))).toEqual({ sourceRef: 'e-1' })
  })
})
