/** NEW-381..390 Web 入口测试 — 长期保存与格式互通组合面板的渲染与
 * 交互主路径。
 *
 * 环境：jsdom；fetch 按 URL 匹配 mock（服务真源在 BFF，后端口径见
 * services/bff/tests/test_new38*.py / test_new390*.py）。 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import {
  BibImportSection,
  EncryptedExportSection,
  FormatCompareSection,
  IndexExportSection,
  JsonFeedSection,
  OfflineSiteSection,
  PreservationCenter,
  ReconciliationSection,
  VolumeSection,
} from '../components/new381/PreservationCenter'

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

const fetchCalls: { url: string; init?: RequestInit; body: string }[] = []
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

function callsTo(url: string): { url: string; init?: RequestInit; body: string }[] {
  return fetchCalls.filter((call) => call.url === url || call.url.startsWith(`${url}?`))
}

beforeEach(() => {
  fetchCalls.length = 0
  routes = []
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    const body = typeof init?.body === 'string' ? init.body : ''
    fetchCalls.push({ url, init, body })
    const route = routes.find((candidate) => candidate.match(url, init))
    if (route) return route.respond(url, init)
    return new Response(JSON.stringify({ error: { type: 'no_route', message: 'no route' } }), {
      status: 404,
      headers: { 'content-type': 'application/json' },
    })
  }) as typeof fetch
})

afterEach(() => {
  cleanup()
})

describe('书目导入（Zotero RDF / RIS）', () => {
  it('预览展示字段映射、重复与不支持字段，确认后导入计数', async () => {
    mockRoute(
      (url) => url.endsWith('/preservation/zotero/preview'),
      () =>
        jsonResponse({
          format: 'zotero_rdf',
          total: 2,
          duplicates: 1,
          unsupportedFields: ['bibo:pages'],
          items: [
            {
              id: 'bib-1',
              format: 'zotero_rdf',
              externalId: 'ABCD1234',
              title: '长期保存的格式迁移研究',
              creators: ['陈, 静'],
              pubYear: '2024',
              publication: '档案学刊',
              publisher: '',
              url: '',
              doi: '',
              itemType: 'journalArticle',
              tags: ['数字保存'],
              unsupportedFields: ['bibo:pages'],
              createdAt: '2026-09-29T00:00:00+00:00',
              duplicate: true,
              duplicateOf: 'bib-0',
              duplicateReason: 'external_id',
            },
          ],
        }),
    )
    mockRoute(
      (url) => url.endsWith('/preservation/zotero/import'),
      () =>
        jsonResponse({
          batchId: 'bibimp-1',
          total: 2,
          imported: 1,
          duplicates: 1,
          failed: 0,
          unsupportedFields: ['bibo:pages'],
        }),
    )
    renderWithQuery(<BibImportSection />)
    const input = screen.getByTestId('n381-bib-content')
    fireEvent.change(input, { target: { value: '<rdf:RDF>…</rdf:RDF>' } })
    fireEvent.click(screen.getByRole('button', { name: '预览字段映射（Zotero RDF）' }))
    await waitFor(() => {
      expect(document.querySelector('[data-n381-bib-preview]')).not.toBeNull()
    })
    expect(screen.getByText(/长期保存的格式迁移研究/)).toBeDefined()
    expect(screen.getByText(/同一引用标识/)).toBeDefined()
    expect(screen.getByText(/bibo:pages/)).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: '导入（Zotero RDF）' }))
    await waitFor(() => {
      expect(screen.getByText(/新增 1，重复跳过 1，失败 0/)).toBeDefined()
    })
    const previewCalls = callsTo('/api/v1/preservation/zotero/preview')
    expect(previewCalls).toHaveLength(1)
    expect(previewCalls[0].body).toContain('rdf:RDF')
  })

  it('解析失败（400）时如实报错而不是假装成功', async () => {
    mockRoute(
      (url) => url.endsWith('/preservation/ris/preview'),
      () =>
        jsonResponse(
          { error: { type: 'invalid_bib_file', message: '未在文件中找到 RIS 条目（TY … ER）。' } },
          400,
        ),
    )
    renderWithQuery(<BibImportSection />)
    fireEvent.change(screen.getByTestId('n381-bib-content'), { target: { value: '垃圾文本' } })
    fireEvent.click(screen.getByRole('button', { name: '预览（RIS）' }))
    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toContain('未在文件中找到 RIS 条目')
    })
  })
})

describe('NEW-383/384 离线站点与 JSON Feed', () => {
  it('离线站点台账展示缺失与违规计数，可生成新集合', async () => {
    mockRoute(
      (url, init) =>
        url.endsWith('/preservation/offline-sites') && init?.method === undefined,
      () =>
        jsonResponse({
          sites: [
            {
              id: 'offsite-1',
              itemRefs: ['bib-1'],
              itemCount: 3,
              violationCount: 1,
              violations: [{ slug: '001-x', target: '../../../escape' }],
              externalLinks: ['https://out.example/x'],
              sha256: 'ab12',
              createdAt: '2026-09-29T00:00:00+00:00',
              missing: ['bib-gone'],
            },
          ],
        }),
    )
    mockRoute(
      (url, init) => url.endsWith('/preservation/offline-sites') && init?.method === 'POST',
      () =>
        jsonResponse({
          id: 'offsite-2',
          itemCount: 1,
          items: [],
          violations: [],
          violationCount: 0,
          externalLinks: [],
          missing: [],
          sha256: 'cd34',
        }),
    )
    renderWithQuery(<OfflineSiteSection />)
    await waitFor(() => {
      expect(screen.getByText(/缺失 1/)).toBeDefined()
    })
    expect(screen.getByText(/违规 1/)).toBeDefined()
    fireEvent.change(screen.getByTestId('n381-offline-bibids'), {
      target: { value: 'bib-1 bib-2' },
    })
    fireEvent.click(screen.getByRole('button', { name: '生成离线资料集' }))
    await waitFor(() => {
      const posts = callsTo('/api/v1/preservation/offline-sites').filter(
        (call) => call.init?.method === 'POST',
      )
      expect(posts).toHaveLength(1)
      expect(JSON.parse(posts[0].body)).toEqual({ bibIds: ['bib-1', 'bib-2'], clipRefs: [] })
    })
  })

  it('JSON Feed 范围说明与台账计数', async () => {
    mockRoute(
      (url) => url.endsWith('/preservation/json-feed/exports'),
      () =>
        jsonResponse({
          exports: [
            {
              id: 'jsonfeed-1',
              scope: 'clips+bib',
              clipCount: 2,
              bibCount: 3,
              fieldsIncluded: ['id', 'title'],
              authorizationScope: '只包含本人资料',
              createdAt: '2026-09-29T00:00:00+00:00',
            },
          ],
        }),
    )
    mockRoute(
      (url, init) => url.endsWith('/preservation/json-feed') && init?.method === 'POST',
      () => jsonResponse({ itemCount: 5, _lumi: {} }),
    )
    renderWithQuery(<JsonFeedSection />)
    await waitFor(() => {
      expect(screen.getByText(/剪藏 2 \/ 书目 3/)).toBeDefined()
    })
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: '生成 JSON Feed 导出' }))
    await waitFor(() => {
      expect(screen.getByText(/共 5 条/)).toBeDefined()
    })
    const posts = callsTo('/api/v1/preservation/json-feed').filter(
      (call) => call.init?.method === 'POST' && !call.url.endsWith('exports'),
    )
    expect(JSON.parse(posts[0].body)).toEqual({ scopes: ['clips'] })
  })
})

describe('NEW-386 格式对照', () => {
  it('逐条展示三格式损失结论', async () => {
    mockRoute(
      (url) => url.endsWith('/preservation/format-compare'),
      () =>
        jsonResponse({
          comparisonId: 'cmp-1',
          compared: 1,
          missing: [],
          items: [
            {
              id: 'bib-1',
              externalId: 'ABCD1234',
              title: '长期保存的格式迁移研究',
              formats: {
                markdown: { bytes: 300, fields: {}, lostFields: [], changedFields: [] },
                html: { bytes: 380, fields: {}, lostFields: [], changedFields: [] },
                text: { bytes: 260, fields: {}, lostFields: ['url'], changedFields: [] },
              },
            },
          ],
        }),
    )
    renderWithQuery(<FormatCompareSection />)
    const idsInput = await waitFor(() => screen.getByTestId('n381-compare-ids'))
    fireEvent.change(idsInput, { target: { value: 'bib-1' } })
    fireEvent.click(screen.getByRole('button', { name: '对照 Markdown / HTML / 纯文本' }))
    await waitFor(() => {
      const summary = screen.getByTestId('n381-compare-summary')
      expect(summary.textContent).toContain('长期保存的格式迁移研究')
      expect(summary.textContent).toContain('text：丢 url')
      expect(summary.textContent).toContain('markdown：无损失')
    })
  })
})

describe('NEW-387 加密导出', () => {
  it('创建 + 双重校验，口令不回显、成功后清空', async () => {
    mockRoute(
      (url, init) =>
        url.endsWith('/preservation/encrypted-exports') && init?.method === undefined,
      () => jsonResponse({ exports: [] }),
    )
    let createCalled = 0
    mockRoute(
      (url, init) =>
        url.endsWith('/preservation/encrypted-exports/verify') &&
        init?.method === 'POST',
      () => jsonResponse({ decryptVerified: true, itemCount: 2, note: 'ok' }),
    )
    mockRoute(
      (url, init) =>
        url.endsWith('/preservation/encrypted-exports') && init?.method === 'POST',
      () => {
        createCalled += 1
        if (createCalled === 1) {
          return jsonResponse({
            id: 'encexp-1',
            itemCount: 2,
            payloadBase64: 'TFVNSUVOQzE=',
            decryptVerified: true,
            format: { kdf: 'PBKDF2', cipher: 'AES-256-GCM', note: 'ok' },
          })
        }
        return jsonResponse({ decryptVerified: true, itemCount: 2, note: 'ok' })
      },
    )
    renderWithQuery(<EncryptedExportSection />)
    await waitFor(() => {
      expect(screen.getByText(/还没有/)).toBeDefined()
    })
    fireEvent.change(screen.getByTestId('n381-enc-ids'), { target: { value: 'bib-1 bib-2' } })
    const pass = screen.getByTestId('n381-enc-pass')
    fireEvent.change(pass, { target: { value: '迁移-口令-2026' } })
    fireEvent.click(screen.getByRole('button', { name: '生成加密包并校验' }))
    await waitFor(() => {
      expect(screen.getByText(/服务端解密校验：通过/)).toBeDefined()
      expect(screen.getByText(/回传校验：通过/)).toBeDefined()
    })
    // 口令即用即弃：成功后输入框清空；输入框本身是 password 类型
    expect((pass as HTMLInputElement).value).toBe('')
    expect((pass as HTMLInputElement).type).toBe('password')
    const bodies = callsTo('/api/v1/preservation/encrypted-exports')
      .filter((call) => call.init?.method === 'POST')
      .map((call) => JSON.parse(call.body) as { passphrase?: string })
    expect(bodies[0].passphrase).toBe('迁移-口令-2026')
  })
})

describe('NEW-388/389 索引导出与分卷', () => {
  it('索引导出说明不含全文，展示校验值', async () => {
    mockRoute(
      (url) => url.endsWith('/preservation/index-export/exports'),
      () => jsonResponse({ exports: [] }),
    )
    mockRoute(
      (url) => url.endsWith('/preservation/index-export'),
      () =>
        jsonResponse({
          recordCount: 4,
          records: [{ externalId: 'ABCD1234', title: 't', sha256: 'f'.repeat(64) }],
          tags: { 数字保存: 1 },
          sources: {},
          excluded: ['abstract', '正文'],
          catalogSha256: 'e'.repeat(64),
          note: '索引导出只含目录、标签、来源与校验值，不含摘要或全文。',
        }),
    )
    renderWithQuery(<IndexExportSection />)
    const buildButton = await waitFor(() =>
      screen.getByRole('button', { name: '生成索引导出' }),
    )
    fireEvent.click(buildButton)
    await waitFor(() => {
      const line = document.querySelector('[data-n381-status="catalog"]')
      expect(line?.textContent).toContain('不含摘要或全文')
      expect(line?.textContent).toContain('4 条')
    })
  })

  it('分卷导出传递容量上限并展示卷数', async () => {
    mockRoute(
      (url) => url.endsWith('/preservation/volumes/sets'),
      () =>
        jsonResponse({
          sets: [
            {
              setId: 'volset-1',
              volumeCount: 3,
              maxVolumeBytes: 65536,
              totalBytes: 123456,
              itemCount: 10,
              createdAt: '2026-09-29T00:00:00+00:00',
            },
          ],
        }),
    )
    mockRoute(
      (url, init) => url.endsWith('/preservation/volumes/export') && init?.method === 'POST',
      () =>
        jsonResponse({
          setManifest: { setId: 'volset-2', volumeCount: 2, itemCount: 12 },
          volumes: [],
        }),
    )
    renderWithQuery(<VolumeSection />)
    await waitFor(() => {
      expect(screen.getByText(/volset-1 · 3 卷 \/ 10 条/)).toBeDefined()
    })
    fireEvent.change(screen.getByTestId('n381-vol-cap'), { target: { value: '128' } })
    fireEvent.click(screen.getByRole('button', { name: '生成分卷' }))
    await waitFor(() => {
      expect(screen.getByText(/volset-2：共 2 卷 \/ 12 条/)).toBeDefined()
    })
    const post = callsTo('/api/v1/preservation/volumes/export').find(
      (call) => call.init?.method === 'POST',
    )
    expect(JSON.parse(post?.body ?? '{}')).toEqual({ itemIds: [], maxVolumeBytes: 131072 })
  })
})

describe('迁移结果逐项对账', () => {
  it('四态逐条展示，确认一条少一条，无一键全收', async () => {
    let confirmDone = false
    mockRoute(
      (url, init) =>
        url.endsWith('/preservation/reconciliations') && init?.method === undefined,
      () =>
        jsonResponse({
          reconciliations: [
            {
              id: 'recon-1',
              source: 'volume:volset-1',
              expectedCount: 3,
              results: [
                { externalId: 'ext-1', title: '甲', status: 'added', detail: '' },
                { externalId: 'ext-2', title: '乙', status: 'failed', detail: '字段超长' },
                { externalId: 'ext-4', title: '', status: 'missing', detail: '在原清单中，但导入结果里没有出现。' },
              ],
              confirmed: confirmDone ? ['ext-1'] : [],
              pendingCount: confirmDone ? 2 : 3,
              status: 'open',
              counts: { added: 1, matched: 0, failed: 1, missing: 1 },
              createdAt: '2026-09-29T00:00:00+00:00',
            },
          ],
        }),
    )
    mockRoute(
      (url) => url.includes('/preservation/reconciliations/recon-1/confirm'),
      () => {
        confirmDone = true
        return jsonResponse({
          id: 'recon-1',
          source: 'volume:volset-1',
          expectedCount: 3,
          results: [],
          confirmed: ['ext-1'],
          pendingCount: 2,
          status: 'open',
          counts: {},
          createdAt: '',
          acceptedNow: 1,
        })
      },
    )
    renderWithQuery(<ReconciliationSection />)
    await waitFor(() => {
      expect(screen.getByText(/待确认 3/)).toBeDefined()
      expect(screen.getByText(/失败：字段超长/)).toBeDefined()
      expect(screen.getByText(/丢失（清单有、导入结果无）/)).toBeDefined()
    })
    const confirmButtons = screen
      .getAllByRole('button')
      .filter((button) => button.textContent === '确认这条')
    expect(confirmButtons).toHaveLength(3)
    fireEvent.click(confirmButtons[0])
    await waitFor(() => {
      expect(screen.getByText('已确认')).toBeDefined()
    })
    const confirmCalls = callsTo('/api/v1/preservation/reconciliations/recon-1/confirm')
    expect(confirmCalls).toHaveLength(1)
    expect(JSON.parse(confirmCalls[0].body)).toEqual({ externalIds: ['ext-1'] })
  })
})

describe('NEW-381..390 组合入口', () => {
  it('八个二级子区全部渲染且默认折叠（零查询）', () => {
    renderWithQuery(<PreservationCenter />)
    for (const label of [
      '书目导入（Zotero RDF / RIS）',
      '离线 HTML 资料集',
      'JSON Feed 个人导出',
      '保存格式对照预览',
      '个人资料包加密导出',
      '个人索引导出',
      '分卷导出',
      '迁移结果逐项对账',
    ]) {
      const toggle = screen.getByRole('button', { name: label })
      expect(toggle.getAttribute('aria-expanded')).toBe('false')
    }
    // 折叠 = 零请求
    expect(fetchCalls).toHaveLength(0)
  })
})
