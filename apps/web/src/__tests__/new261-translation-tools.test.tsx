/** NEW-261..270 Web 入口测试 — 翻译工作流工具组合的渲染与交互主路径。
 *
 * 环境：jsdom；fetch 按 URL 匹配 mock（服务真源在 BFF，后端口径见
 * services/bff/tests/test_new26*.py）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { TranslationSegmentState } from '../api/types'
import { New261TranslationTools } from '../components/new261/New261TranslationTools'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderExpanded(ui: React.ReactElement): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
  // 情境展开（MASTER §6）：默认折叠零查询；本套件断言针对展开后的子面板。
  fireEvent.click(screen.getByRole('button', { name: /翻译工作流工具（/ }))
}

const SEGMENTS: TranslationSegmentState[] = [
  {
    index: 0,
    status: 'success',
    translatedText: '第一段机器译文',
    userRevision: '第一段人工修订',
    cached: false,
    noTranslate: false,
    revisionStale: false,
    protectedTerms: [],
  },
  {
    index: 1,
    status: 'success',
    translatedText: '第二段机器译文',
    userRevision: null,
    cached: true,
    noTranslate: false,
    revisionStale: false,
    protectedTerms: [],
  },
  {
    index: 2,
    status: 'not_generated',
    translatedText: null,
    userRevision: null,
    cached: false,
    noTranslate: false,
    revisionStale: false,
    protectedTerms: [],
  },
]

const BLOCKS = [
  { index: 0, text: 'First paragraph about Project Helios.' },
  { index: 1, text: 'Second paragraph mentions Ada Lovelace.' },
  { index: 2, text: 'Third paragraph awaits translation.' },
]

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

function renderTools(): void {
  renderExpanded(
    <New261TranslationTools
      entryRef="entry-abc"
      segments={SEGMENTS}
      blocks={BLOCKS}
      feedUrl="https://example.org/feed.xml"
    />,
  )
}

describe('NEW-261..270 翻译工作流工具组合', () => {
  it('折叠态零请求；展开后十组面板挂载', () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <New261TranslationTools entryRef="entry-abc" segments={[]} blocks={null} feedUrl={null} />
      </QueryClientProvider>,
    )
    const toggle = screen.getByRole('button', { name: /翻译工作流工具（/ })
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(fetchCalls.length).toBe(0)
    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByLabelText('术语冲突与生效译法（NEW-261）')).toBeTruthy()
    expect(screen.getByLabelText('翻译完整性报告（NEW-270）')).toBeTruthy()
  })

  it('NEW-261 冲突清单带来源/范围；按来源登记生效译法（POST 含 sourceUrl）', async () => {
    mockRoute(
      (url) => url === '/api/v1/glossary/conflicts',
      () =>
        jsonResponse({
          conflicts: [
            {
              term: 'Helios',
              variants: [
                { termId: 'gt-1', definition: '太阳神号', sourceRef: null, protect: false, updatedAt: 't1' },
                { termId: 'gt-2', definition: '赫利俄斯探测器', sourceRef: 'astro-feed', protect: true, updatedAt: 't2' },
              ],
              chosen: undefined,
            },
          ],
        }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/glossary/conflicts/choice' && init?.method === 'POST',
      (url, init) => {
        const body = JSON.parse(String(init?.body))
        return jsonResponse({ ...body, updatedAt: 't3' })
      },
    )
    renderTools()
    const choose = await screen.findByLabelText('选择译法：赫利俄斯探测器')
    fireEvent.click(choose)
    const scopeSelect = screen.getByLabelText('生效范围：Helios') as HTMLSelectElement
    await waitFor(() => expect(scopeSelect.options.length).toBeGreaterThan(0))
    fireEvent.change(scopeSelect, { target: { value: 'source' } })
    fireEvent.change(screen.getByLabelText('来源地址：Helios'), {
      target: { value: 'https://example.org/feed.xml' },
    })
    fireEvent.click(screen.getByText('设为生效译法'))
    await waitFor(() => expect(screen.getByText(/已为当前来源登记生效译法/)).toBeTruthy())
    const post = fetchCalls.find((c) => c.url === '/api/v1/glossary/conflicts/choice' && c.init?.method === 'POST')
    expect(JSON.parse(String(post?.init?.body))).toEqual({
      term: 'Helios',
      chosenTermId: 'gt-2',
      scope: 'source',
      sourceUrl: 'https://example.org/feed.xml',
    })
  })

  it('NEW-262 放弃修订并重翻（POST body regenerate=true）+ 决定台账可见', async () => {
    mockRoute(
      (url) => url === '/api/v1/entries/entry-abc/translation/revision-decisions',
      () =>
        jsonResponse({
          decisions: [
            { id: 'trd-1', blockIndex: 3, overwrittenText: '旧修订', supersededMachineText: '旧机器', createdAt: 't0' },
          ],
        }),
    )
    mockRoute(
      (url, init) =>
        url === '/api/v1/entries/entry-abc/translation/segments/0/revision/discard' && init?.method === 'POST',
      () =>
        jsonResponse({
          id: 'trd-2',
          blockIndex: 0,
          overwrittenText: '第一段人工修订',
          supersededMachineText: '第一段机器译文',
          createdAt: 't1',
          regenerated: { status: 'success', translatedText: '重翻稿', cached: false },
        }),
    )
    renderTools()
    fireEvent.click(await screen.findByText('放弃修订并重翻'))
    await waitFor(() => expect(screen.getByText(/已放弃第 1 段修订并重翻成功/)).toBeTruthy())
    const post = fetchCalls.find((c) => c.url?.endsWith('/revision/discard'))
    expect(JSON.parse(String(post?.init?.body))).toEqual({ regenerate: true })
    fireEvent.click(screen.getByText(/决定台账（1 条）/))
    expect(screen.getByText(/第 4 段 · 放弃于 t0/)).toBeTruthy()
  })

  it('NEW-263 标记漏译进入待复核队列；复核显式出队', async () => {
    // 单一真源：entry 反馈清单与待复核队列共用（open 进队列，resolved 出队）。
    let feedbackList: Array<Record<string, unknown>> = [
      {
        id: 'tf-1',
        entryRef: 'entry-abc',
        blockIndex: 0,
        issueKind: 'omission',
        note: '已有的漏译标记',
        sourceExcerpt: 'First…',
        machineExcerpt: '第一段…',
        revisedExcerpt: null,
        status: 'open',
        createdAt: 't1',
        resolvedAt: null,
      },
    ]
    mockRoute(
      (url, init) =>
        url === '/api/v1/entries/entry-abc/translation/feedback' && (!init?.method || init.method === 'GET'),
      () => jsonResponse({ feedback: feedbackList }),
    )
    mockRoute(
      (url) => url === '/api/v1/translation/feedback/queue',
      () => jsonResponse({ queue: feedbackList.filter((item) => item.status === 'open') }),
    )
    mockRoute(
      (url, init) =>
        url === '/api/v1/entries/entry-abc/translation/segments/0/feedback' && init?.method === 'POST',
      (url, init) => {
        const item = {
          id: 'tf-2',
          entryRef: 'entry-abc',
          blockIndex: 0,
          ...JSON.parse(String(init?.body)),
          sourceExcerpt: null,
          machineExcerpt: null,
          revisedExcerpt: null,
          status: 'open',
          createdAt: 't2',
          resolvedAt: null,
        }
        feedbackList = [...feedbackList, item]
        return jsonResponse(item)
      },
    )
    mockRoute(
      (url, init) => url === '/api/v1/translation/feedback/tf-1/resolve' && init?.method === 'POST',
      () => {
        feedbackList = feedbackList.map((item) =>
          item.id === 'tf-1' ? { ...item, status: 'resolved', resolvedAt: 't3' } : item,
        )
        return jsonResponse({ id: 'tf-1', status: 'resolved', resolvedAt: 't3' })
      },
    )
    renderTools()
    fireEvent.change(await screen.findByLabelText('问题补充说明'), { target: { value: '末句没了' } })
    fireEvent.click(screen.getByText('标记问题'))
    await waitFor(() => expect(screen.getByText(/已标记第 1 段为「漏译」/)).toBeTruthy())
    const post = fetchCalls.find((c) => c.url === '/api/v1/entries/entry-abc/translation/segments/0/feedback')
    expect(JSON.parse(String(post?.init?.body))).toEqual({ issueKind: 'omission', note: '末句没了' })
    await waitFor(() => expect(screen.getByText(/本人待复核队列共 2 条/)).toBeTruthy())
    fireEvent.click(screen.getAllByText('复核完成')[0])
    await waitFor(() => expect(screen.getByText('已复核完成，移出队列。')).toBeTruthy())
    await waitFor(() => expect(screen.getByText(/本人待复核队列共 1 条/)).toBeTruthy())
  })

  it('NEW-264 显式样本对照：逐侧结果/耗时；未配置侧诚实 unavailable', async () => {
    mockRoute(
      (url) => url === '/api/v1/translation/capability-probe' && (!fetchCalls.some((c) => c.url === url && c.init?.method === 'POST')),
      () => jsonResponse({ probes: [] }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/translation/capability-probe' && init?.method === 'POST',
      () =>
        jsonResponse({
          id: 'tcp-1',
          samples: ['Hello world.'],
          sides: {
            ai: {
              configured: true,
              samples: [{ index: 0, ok: true, text: '你好，世界。', elapsedMs: 812 }],
            },
            libretranslate: { configured: false, reason: 'LibreTranslate 未配置 URL。' },
          },
          available: true,
          reason: '',
          createdAt: 't1',
        }),
    )
    renderTools()
    fireEvent.change(await screen.findByLabelText('样本 1'), { target: { value: 'Hello world.' } })
    fireEvent.click(screen.getByText('运行对照（1 段）'))
    await waitFor(() => expect(screen.getByText(/你好，世界。/)).toBeTruthy())
    expect(screen.getByText(/812 ms/)).toBeTruthy()
    expect(screen.getByText(/未配置 · LibreTranslate 未配置 URL。/)).toBeTruthy()
    const post = fetchCalls.find((c) => c.url === '/api/v1/translation/capability-probe' && c.init?.method === 'POST')
    expect(JSON.parse(String(post?.init?.body))).toEqual({ samples: ['Hello world.'] })
  })

  it('NEW-265 登记单价（PUT）后预估：计费/免费拆分 + 费用估算诚实展示', async () => {
    mockRoute(
      (url) => url === '/api/v1/translation/budget/settings' && (!fetchCalls.some((c) => c.url === url && c.init?.method === 'PUT')),
      () => jsonResponse({ pricePer1kChars: null, currency: '', updatedAt: '' }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/translation/budget/settings' && init?.method === 'PUT',
      (url, init) => jsonResponse({ ...JSON.parse(String(init?.body)), updatedAt: 't1' }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/translation/budget/estimate' && init?.method === 'POST',
      () =>
        jsonResponse({
          totalBlocks: 3,
          chargeableBlocks: 2,
          cachedBlocks: 1,
          noTranslateBlocks: 0,
          revisedBlocks: 0,
          totalChars: 96,
          chargeableChars: 64,
          pricePer1kChars: 0.5,
          currency: 'USD',
          estimatedCost: 0.032,
          engine: 'ai',
          note: '',
        }),
    )
    renderTools()
    fireEvent.change(await screen.findByLabelText('每千字符单价'), { target: { value: '0.5' } })
    fireEvent.change(screen.getByLabelText('币种'), { target: { value: 'USD' } })
    fireEvent.click(screen.getByText('保存单价设置'))
    await waitFor(() => expect(screen.getByText('已登记估算单价。')).toBeTruthy())
    const put = fetchCalls.find((c) => c.url === '/api/v1/translation/budget/settings' && c.init?.method === 'PUT')
    expect(JSON.parse(String(put?.init?.body))).toEqual({ pricePer1kChars: 0.5, currency: 'USD' })
    fireEvent.click(screen.getByText('预估当前范围'))
    await waitFor(() => expect(screen.getByText(/预估费用 ≈ 0.032 USD/)).toBeTruthy())
    expect(screen.getByText(/缓存 1 · 不翻译 0 · 已有修订 0 段零费用/)).toBeTruthy()
    const post = fetchCalls.find((c) => c.url === '/api/v1/translation/budget/estimate')
    const body = JSON.parse(String(post?.init?.body))
    expect(body.entryRef).toBe('entry-abc')
    expect(body.blocks).toHaveLength(3)
  })

  it('NEW-266 选段入队按序登记（PUT indexes）；执行只发交集并报告缓存零调用', async () => {
    let queueIndexes: number[] = []
    mockRoute(
      (url, init) =>
        url === '/api/v1/entries/entry-abc/translation/priority-queue' && (!init?.method || init.method === 'GET'),
      () => jsonResponse({ queue: queueIndexes.map((index) => ({ index, addedAt: 't1' })) }),
    )
    mockRoute(
      (url, init) =>
        url === '/api/v1/entries/entry-abc/translation/priority-queue' && init?.method === 'PUT',
      (url, init) => {
        queueIndexes = JSON.parse(String(init?.body)).indexes
        return jsonResponse({ queue: queueIndexes.map((index) => ({ index, addedAt: 't1' })) })
      },
    )
    mockRoute(
      (url, init) => url === '/api/v1/entries/entry-abc/translation/priority-queue/run' && init?.method === 'POST',
      (url, init) => {
        const body = JSON.parse(String(init?.body)) as { blocks: { index: number }[] }
        // BFF 契约：只翻「队列 ∩ 提交块集合」，queuedCount = 交集数。
        const sent = body.blocks.filter((block) => queueIndexes.includes(block.index))
        return jsonResponse({
          queuedCount: sent.length,
          skippedMissingText: [],
          queuedStates: sent.map((block) => ({
            index: block.index,
            status: block.index === 1 ? 'success' : 'failed',
            translatedText: block.index === 1 ? '缓存稿' : null,
            failureType: block.index === 1 ? null : 'upstream',
            cached: block.index === 1,
          })),
        })
      },
    )
    renderTools()
    fireEvent.click(await screen.findByLabelText('选择第 2 段'))
    fireEvent.click(screen.getByLabelText('选择第 3 段'))
    fireEvent.click(screen.getByText('按此顺序加入队列（2 段）'))
    await waitFor(() => expect(screen.getByText(/已按顺序登记 2 段/)).toBeTruthy())
    const put = fetchCalls.find((c) => c.url === '/api/v1/entries/entry-abc/translation/priority-queue' && c.init?.method === 'PUT')
    expect(JSON.parse(String(put?.init?.body))).toEqual({ indexes: [1, 2] })
    fireEvent.click(screen.getByText('执行队列'))
    await waitFor(() => expect(screen.getByText(/发送 2 段；成功 1 段/)).toBeTruthy())
    expect(screen.getByText(/缓存命中 1 段零调用/)).toBeTruthy()
  })

  it('NEW-267 登记例外显示命中数；撤销恢复默认保护', async () => {
    let hasException = false
    mockRoute(
      (url, init) =>
        url === '/api/v1/entries/entry-abc/translation/protect-exceptions' && (!init?.method || init.method === 'GET'),
      () =>
        hasException
          ? jsonResponse({ exceptions: [{ term: 'Helios', createdAt: 't1' }], hits: [{ term: 'Helios', hitSegments: 1 }] })
          : jsonResponse({ exceptions: [], hits: [] }),
    )
    mockRoute(
      (url, init) =>
        url === '/api/v1/entries/entry-abc/translation/protect-exceptions' && init?.method === 'POST',
      () => {
        hasException = true
        return jsonResponse({ term: 'Helios', createdAt: 't1' })
      },
    )
    mockRoute(
      (url, init) =>
        url === '/api/v1/entries/entry-abc/translation/protect-exceptions/Helios' && init?.method === 'DELETE',
      () => {
        hasException = false
        return jsonResponse({ removed: true })
      },
    )
    renderTools()
    fireEvent.change(await screen.findByLabelText('豁免术语'), { target: { value: 'Helios' } })
    fireEvent.click(screen.getByText('登记例外'))
    await waitFor(() => expect(screen.getByText(/例外已登记：「Helios」/)).toBeTruthy())
    await waitFor(() => expect(screen.getByText(/命中 1 个不同源段/)).toBeTruthy())
    fireEvent.click(screen.getByText('撤销例外'))
    await waitFor(() => expect(screen.getByText(/例外已撤销，该术语恢复全局默认保护/)).toBeTruthy())
  })

  it('NEW-268 确认后导出附原文/来源/机器人工标记（未确认按钮禁用）', async () => {
    mockRoute(
      (url) => url === '/api/v1/entries/entry-abc/translation/quote-exports',
      () =>
        jsonResponse({
          exports: [
            {
              id: 'tqe-1',
              entryRef: 'entry-abc',
              blockIndex: 0,
              sourceText: 'First paragraph…',
              translatedText: '第一段人工修订',
              humanRevised: true,
              sourceUrl: 'https://example.org/post/1',
              feedTitle: '示例源',
              format: 'markdown',
              createdAt: 't1',
            },
          ],
        }),
    )
    mockRoute(
      (url, init) =>
        url === '/api/v1/entries/entry-abc/translation/segments/0/quote-export' && init?.method === 'POST',
      () =>
        jsonResponse({
          id: 'tqe-2',
          entryRef: 'entry-abc',
          blockIndex: 0,
          sourceText: 'First paragraph about Project Helios.',
          translatedText: '第一段人工修订',
          humanRevised: true,
          sourceUrl: 'https://example.org/feed.xml',
          feedTitle: '示例源',
          format: 'markdown',
          rendered: '> 第一段人工修订\n\n— 原文：First paragraph…',
          createdAt: 't2',
        }),
    )
    renderTools()
    const exportButton = await screen.findByText('确认并导出')
    expect((exportButton as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByLabelText('我确认此译文可引用'))
    expect((exportButton as HTMLButtonElement).disabled).toBe(false)
    fireEvent.click(exportButton)
    await waitFor(() => expect(screen.getByText(/已导出第 1 段（人工修订）/)).toBeTruthy())
    const post = fetchCalls.find((c) => c.url?.endsWith('/quote-export'))
    expect(JSON.parse(String(post?.init?.body))).toEqual({
      blockText: 'First paragraph about Project Helios.',
      format: 'markdown',
      confirmed: true,
    })
    fireEvent.click(screen.getByText(/导出台账（1 条）/))
    expect(screen.getByText(/人工修订 · 示例源/)).toBeTruthy()
  })

  it('NEW-269 更正来源语言（PUT scope/refKey/language）；提示只影响其后新生成', async () => {
    mockRoute(
      (url) => url === '/api/v1/translation/language-overrides' && (!fetchCalls.some((c) => c.url === url && c.init?.method === 'PUT')),
      () => jsonResponse({ overrides: [] }),
    )
    mockRoute(
      (url) => url === '/api/v1/entries/entry-abc/translation/language-override',
      () => jsonResponse({ language: null }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/translation/language-overrides' && init?.method === 'PUT',
      (url, init) => jsonResponse({ ...JSON.parse(String(init?.body)), createdAt: 't0', updatedAt: 't1' }),
    )
    renderTools()
    await waitFor(() => expect(screen.getByText(/当前生效识别语言：自动识别（无更正）/)).toBeTruthy())
    const scopeSelect = screen.getByLabelText('更正范围') as HTMLSelectElement
    await waitFor(() => expect(scopeSelect.options.length).toBeGreaterThan(0))
    fireEvent.change(scopeSelect, { target: { value: 'source' } })
    fireEvent.change(screen.getByLabelText('更正为的语言代码'), { target: { value: 'pt-BR' } })
    fireEvent.click(screen.getByText('登记更正'))
    await waitFor(() => expect(screen.getByText(/已更正：整个来源其后新生成按 pt-BR 处理/)).toBeTruthy())
    const put = fetchCalls.find((c) => c.url === '/api/v1/translation/language-overrides' && c.init?.method === 'PUT')
    expect(JSON.parse(String(put?.init?.body))).toEqual({
      scope: 'source',
      refKey: 'https://example.org/feed.xml',
      language: 'pt-BR',
    })
  })

  it('NEW-270 完整性报告逐段分类；补译只发缺段并报告补成功数', async () => {
    let filled = false
    mockRoute(
      (url, init) =>
        url === '/api/v1/entries/entry-abc/translation/completeness/report' && init?.method === 'POST',
      () =>
        jsonResponse({
          id: 'tcr-1',
          entryRef: 'entry-abc',
          total: 3,
          translated: 1,
          failed: 0,
          missing: 1,
          skipped: 0,
          translatedIndexes: [0],
          failedIndexes: [],
          missingIndexes: [2],
          skippedIndexes: [],
          filled: 0,
          createdAt: 't1',
        }),
    )
    mockRoute(
      (url, init) =>
        url === '/api/v1/entries/entry-abc/translation/completeness/fill' && init?.method === 'POST',
      (url, init) => {
        filled = true
        const body = JSON.parse(String(init?.body)) as { blocks: unknown[] }
        return jsonResponse({
          id: 'tcr-2',
          entryRef: 'entry-abc',
          total: 3,
          translated: 2,
          failed: 0,
          missing: 0,
          skipped: 0,
          translatedIndexes: [0, 2],
          failedIndexes: [],
          missingIndexes: [],
          skippedIndexes: [],
          filled: 1,
          createdAt: 't2',
          _sentBlocks: body.blocks.length,
        })
      },
    )
    mockRoute(
      (url) => url === '/api/v1/entries/entry-abc/translation/completeness/reports',
      () =>
        jsonResponse({
          reports: [
            { id: 'tcr-2', entryRef: 'entry-abc', total: 3, translated: 2, failed: 0, missing: 0, skipped: 0, filled: 1, createdAt: 't2' },
            { id: 'tcr-1', entryRef: 'entry-abc', total: 3, translated: 1, failed: 0, missing: 1, skipped: 0, filled: 0, createdAt: 't1' },
          ],
        }),
    )
    renderTools()
    fireEvent.click(await screen.findByText('生成完整性报告'))
    await waitFor(() => expect(screen.getByText(/完成 1 · 缺失 1 · 失败 0 · 跳过（不翻译）0/)).toBeTruthy())
    const completenessSection = screen.getByLabelText('翻译完整性报告（NEW-270）')
    expect(within(completenessSection).getByText(/缺失：/)).toBeTruthy()
    expect(within(completenessSection).getByText('第 3 段')).toBeTruthy()
    fireEvent.click(screen.getByText('补译缺失段（1 段）'))
    await waitFor(() => expect(screen.getByText(/补译完成：本次补成功 1 段（只发送缺失\/失败段）/)).toBeTruthy())
    expect(filled).toBe(true)
    const fillPost = fetchCalls.find((c) => c.url?.endsWith('/completeness/fill'))
    const fillBody = JSON.parse(String(fillPost?.init?.body)) as { blocks: { index: number }[] }
    expect(fillBody.blocks).toHaveLength(3)
    await waitFor(() =>
      expect(within(completenessSection).getByText(/完成 2\/3 · 缺 0 · 败 0 · 补成功 1/)).toBeTruthy(),
    )
  })
})
