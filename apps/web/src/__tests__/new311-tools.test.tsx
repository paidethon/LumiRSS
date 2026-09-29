/** NEW-311..320 Web 入口测试 — 剪藏/书签资料工具组的渲染与交互主路径。
 *
 * 环境：jsdom；fetch 按 URL 匹配 mock（服务真源在 BFF，后端口径见
 * tests/test_new31*.py / test_new320*.py）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { New311BookmarkTools } from '../components/new311/New311BookmarkTools'
import { New311ClipTools } from '../components/new311/New311ClipTools'
import { New311SnapshotTextTools } from '../components/new311/New311SnapshotTextTools'

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

function lastCall(url: string): RequestInit {
  const calls = callsTo(url)
  expect(calls.length, `expected a fetch call to ${url}`).toBeGreaterThan(0)
  return calls[calls.length - 1]?.init ?? {}
}

/** 展开组合面板 + 指定子工具（两级情境展开）。 */
function expand(mainName: RegExp, subsectionId: string): void {
  fireEvent.click(screen.getByRole('button', { name: mainName }))
  const toggles = screen
    .getAllByRole('button')
    .filter((button) => {
      const host = button.closest('[data-new311-subsection]')
      return host !== null && host.getAttribute('data-new311-subsection') === subsectionId
    })
  expect(toggles.length).toBeGreaterThan(0)
  fireEvent.click(toggles[0])
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

describe('NEW-311..320 剪藏与书签资料工具组', () => {
  it('折叠态零请求；aria-expanded 随开关翻转（情境展开）', () => {
    renderWithQuery(
      <div>
        <New311BookmarkTools />
        <New311ClipTools />
      </div>,
    )
    const bookmarkToggle = screen.getByRole('button', { name: /书签资料工具（/ })
    const clipToggle = screen.getByRole('button', { name: /剪藏资料工具（/ })
    expect(bookmarkToggle.getAttribute('aria-expanded')).toBe('false')
    expect(clipToggle.getAttribute('aria-expanded')).toBe('false')
    expect(fetchCalls).toHaveLength(0)
    fireEvent.click(bookmarkToggle)
    expect(screen.getByRole('button', { name: /书签资料工具（/ }).getAttribute('aria-expanded')).toBe('true')
    fireEvent.click(screen.getByRole('button', { name: /书签资料工具（/ }))
    expect(screen.getByRole('button', { name: /书签资料工具（/ }).getAttribute('aria-expanded')).toBe('false')
    expect(fetchCalls.map((c) => `${c.init?.method ?? 'GET'} ${c.url}`)).toEqual([])
  })

  it('NEW-312 选区剪藏包：空行分段为多条选区，POST 不含抓取语义', async () => {
    mockRoute(
      (url) => url === '/api/v1/library/clip-selections',
      () => jsonResponse({ id: 'pkg1', url: 'https://p.example/a', pageTitle: '页', clipRef: null, createdAt: 't', selections: [{ seq: 0, text: '第一段', note: '' }, { seq: 1, text: '第二段', note: '' }] }, 201),
    )
    renderWithQuery(<New311ClipTools />)
    expand(/剪藏资料工具（/, 'selection')
    fireEvent.change(screen.getByLabelText('页面 URL'), {
      target: { value: 'https://p.example/a' },
    })
    fireEvent.change(screen.getByLabelText('选中文字（空行分段，每段一段选区）'), {
      target: { value: '第一段\n\n第二段' },
    })
    fireEvent.click(screen.getByRole('button', { name: '保存选区（不抓整页）' }))
    await waitFor(() =>
      expect(screen.getByText(/选区剪藏包已保存：2 段选区/)).toBeTruthy(),
    )
    const init = lastCall('/api/v1/library/clip-selections')
    expect(init.method).toBe('POST')
    const body = JSON.parse(String(init.body))
    expect(body.selections.map((s: { text: string }) => s.text)).toEqual(['第一段', '第二段'])
    expect(body.clipRef).toBeNull()
  })

  it('NEW-311 目录导入：预览目录映射与重复，确认按勾选目录执行', async () => {
    mockRoute(
      (url, init) => url === '/api/v1/library/bookmarks/import/preview' && init?.method === 'POST',
      () =>
        jsonResponse({
          total: 3,
          validTotal: 3,
          folderMap: [{ path: '技术', count: 2 }, { path: '设计', count: 1 }],
          duplicates: [{ url: 'https://a.example/1', title: '一', folderPath: '技术', inFile: true, inLibrary: false }],
          invalid: [],
          honestyNote: '预览零写入',
        }),
    )
    mockRoute(
      (url) => url.startsWith('/api/v1/library/bookmarks/import/sets'),
      (_url, init) => {
        expect(init?.method).toBe('POST')
        expect(String(init?.body)).toContain('<DT><A')
        return jsonResponse({ id: 'set1', total: 2, imported: 2, skipped: 0, folders: ['技术'] }, 201)
      },
    )
    renderWithQuery(<New311BookmarkTools />)
    expand(/书签资料工具（/, 'import')
    const fileInput = screen.getByLabelText('选择书签导出文件') as HTMLInputElement
    const file = new File(['<DT><A HREF="https://a.example/1">一</A>'], 'bookmarks.html', {
      type: 'text/html',
    })
    Object.defineProperty(file, 'text', { value: async () => '<DT><A HREF="https://a.example/1">一</A>' })
    fireEvent.change(fileInput, { target: { files: [file] } })
    await waitFor(() => expect(screen.getByText(/共 3 条/)).toBeTruthy())
    expect(screen.getByText(/文件内重复/)).toBeTruthy()

    fireEvent.click(screen.getByLabelText('导入目录：技术'))
    fireEvent.click(screen.getByRole('button', { name: '确认导入勾选目录' }))
    await waitFor(() => expect(screen.getByText(/新增 2 条，跳过 0 条/)).toBeTruthy())
    expect(lastCall('/api/v1/library/bookmarks/import/preview')).toBeTruthy()
    expect(callsTo('/api/v1/library/bookmarks/import/sets')[0]?.url).toContain('folder=')
  })

  it('NEW-315 链接批量替换：预览 → 执行 → 撤销本批', async () => {
    mockRoute(
      (url) => url === '/api/v1/library/bookmarks/link-replace/preview',
      () => jsonResponse({ changes: [{ ref: 'library:u1', title: '旧站', before: 'https://old.example/x', after: 'https://new.example/x' }] }),
    )
    mockRoute(
      (url) => url === '/api/v1/library/bookmarks/link-replace/apply',
      () => jsonResponse({ id: 'batch1', changed: 1, conflicts: [] }),
    )
    mockRoute(
      (url) => url === '/api/v1/library/bookmarks/link-replace/batches/batch1/undo',
      () => jsonResponse({ id: 'batch1', restored: 1 }),
    )
    renderWithQuery(<New311BookmarkTools />)
    expand(/书签资料工具（/, 'link-replace')
    fireEvent.change(screen.getByLabelText('旧域'), { target: { value: 'old.example.com' } })
    fireEvent.change(screen.getByLabelText('新域'), { target: { value: 'new.example.com' } })
    fireEvent.click(screen.getByRole('button', { name: '预览变化' }))
    await waitFor(() => expect(screen.getByText(/https:\/\/old.example\/x → https:\/\/new.example\/x/)).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '执行替换（1 条）' }))
    await waitFor(() => expect(screen.getByText(/已替换 1 条/)).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '撤销本批' }))
    await waitFor(() => expect(screen.getByText(/已撤销本批（恢复 1 条）/)).toBeTruthy())
    expect(lastCall('/api/v1/library/bookmarks/link-replace/apply').method).toBe('POST')
    expect(lastCall('/api/v1/library/bookmarks/link-replace/batches/batch1/undo').method).toBe('POST')
  })

  it('NEW-316 意图字段：记录意图 + 按用途筛选列表', async () => {
    mockRoute(
      (url, init) => url === '/api/v1/library/bookmark-intents' && (init?.method ?? 'GET') === 'GET',
      () => jsonResponse({ items: [{ ref: 'library:u2', title: '周末读的架构文', url: 'https://a.example/arch', reason: '复盘', whenToUse: '周末' }], total: 1 }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/library/bookmarks/u1/intent' && init?.method === 'PUT',
      () => jsonResponse({ ref: 'library:u1', title: '新记录', url: null, reason: '面试', whenToUse: '周末' }),
    )
    renderWithQuery(<New311BookmarkTools />)
    expand(/书签资料工具（/, 'intent')
    await waitFor(() => expect(screen.getByText(/周末读的架构文/)).toBeTruthy())
    fireEvent.change(screen.getByLabelText('书签 ref（library:…）'), { target: { value: 'library:u1' } })
    fireEvent.change(screen.getByLabelText('为什么保存'), { target: { value: '面试' } })
    fireEvent.click(screen.getByRole('button', { name: '记录意图' }))
    await waitFor(() => expect(screen.getByText('意图已记录。')).toBeTruthy())
    const init = lastCall('/api/v1/library/bookmarks/u1/intent')
    expect(init.method).toBe('PUT')
    expect(JSON.parse(String(init.body))).toEqual({ reason: '面试', whenToUse: '' })
  })

  it('NEW-320 失效替代关联：记录替代并展示变更史（旧链接保留）', async () => {
    mockRoute(
      (url) => url === '/api/v1/library/bookmarks/u3/replacement' && callsTo(url).length === 0,
      () => jsonResponse({ ref: 'library:u3', title: '旧', oldUrl: 'https://dead.example/x', oldLinkPreserved: true, history: [] }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/library/bookmarks/u3/replacement' && init?.method === 'POST',
      () => jsonResponse({ id: 'r1', ref: 'library:u3', oldUrl: 'https://dead.example/x', newUrl: 'https://alive.example/x', reason: '原站下线' }, 201),
    )
    renderWithQuery(<New311BookmarkTools />)
    expand(/书签资料工具（/, 'replacement')
    fireEvent.change(screen.getByLabelText('书签 ref（library:…）'), { target: { value: 'library:u3' } })
    fireEvent.change(screen.getByLabelText('新来源地址'), { target: { value: 'https://alive.example/x' } })
    fireEvent.change(screen.getByLabelText('替换理由'), { target: { value: '原站下线' } })
    fireEvent.click(screen.getByRole('button', { name: '记录替代' }))
    await waitFor(() => expect(screen.getByText(/旧链接原样保留/)).toBeTruthy())
    const init = lastCall('/api/v1/library/bookmarks/u3/replacement')
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ newUrl: 'https://alive.example/x', reason: '原站下线' })
  })

  it('NEW-313 候选对照：双候选并列，选择后调用 choose', async () => {
    mockRoute(
      (url, init) => url === '/api/v1/library/clips/c1/extract-compare' && init?.method === 'POST',
      () =>
        jsonResponse({
          clipRef: 'library:c1',
          candidates: [
            { id: 'cand-a', strategy: 'article', title: '', charCount: 900, preview: '评分提取预览', chosen: false },
            { id: 'cand-b', strategy: 'fulltext', title: '', charCount: 1500, preview: '保真全文预览', chosen: false },
          ],
          honestyNote: '选择只切换展示版本',
        }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/library/clips/c1/extract-compare/cand-b/choose' && init?.method === 'POST',
      () => jsonResponse({ chosenId: 'cand-b', appliedAt: 't', note: '已切换展示版本（修订槽）' }),
    )
    renderWithQuery(<New311ClipTools />)
    expand(/剪藏资料工具（/, 'extract-compare')
    fireEvent.change(screen.getByLabelText('剪藏 ref（library:…）'), { target: { value: 'library:c1' } })
    fireEvent.click(screen.getByRole('button', { name: '抓取并对照两种提取' }))
    await waitFor(() => expect(screen.getByText(/评分提取（900 字）/)).toBeTruthy())
    expect(screen.getByText(/保真全文（1500 字）/)).toBeTruthy()
    fireEvent.click(screen.getAllByRole('button', { name: '选这个版本' })[1])
    await waitFor(() => expect(screen.getByText(/已切换展示版本/)).toBeTruthy())
    expect(lastCall('/api/v1/library/clips/c1/extract-compare/cand-b/choose').method).toBe('POST')
  })

  it('NEW-317 重复合并：组内选保留侧与并入侧后合并', async () => {
    mockRoute(
      (url) => url === '/api/v1/library/clip-duplicates',
      () =>
        jsonResponse({
          groups: [
            {
              key: 'site.example/post',
              items: [
                { ref: 'library:k1', url: 'https://site.example/post', title: '主剪藏', textChars: 100 },
                { ref: 'library:m1', url: 'https://site.example/post?utm=x', title: '变体', textChars: 90 },
              ],
            },
          ],
          groupCount: 1,
        }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/library/clips/merge' && init?.method === 'POST',
      () => jsonResponse({ keptRef: 'library:k1', mergedRefs: ['library:m1'], metaPolicy: 'newest', carriedSelections: 2, mergedAt: 't' }),
    )
    renderWithQuery(<New311ClipTools />)
    expand(/剪藏资料工具（/, 'merge')
    await waitFor(() => expect(screen.getByText('主剪藏')).toBeTruthy())
    fireEvent.click(screen.getByLabelText('保留：主剪藏'))
    fireEvent.click(screen.getByLabelText('并入：变体'))
    fireEvent.change(screen.getByLabelText('合并元数据策略'), { target: { value: 'newest' } })
    fireEvent.click(screen.getByRole('button', { name: '合并所选（1）' }))
    await waitFor(() => expect(screen.getByText(/选段迁移 2 段/)).toBeTruthy())
    const init = lastCall('/api/v1/library/clips/merge')
    expect(JSON.parse(String(init.body))).toEqual({
      keepRef: 'library:k1',
      mergeRefs: ['library:m1'],
      metaPolicy: 'newest',
    })
  })

  it('NEW-318 图片选择器：清单体积如实展示，只提交勾选图片', async () => {
    mockRoute(
      (url, init) => url === '/api/v1/library/clips/image-manifest' && init?.method === 'POST',
      () =>
        jsonResponse({
          url: 'https://g.example/a',
          finalUrl: 'https://g.example/a',
          images: [
            { src: 'https://cdn.example/a.jpg', alt: '首图', bytes: 120_000 },
            { src: 'https://cdn.example/b.jpg', alt: '', bytes: null },
          ],
          imageCount: 2,
          honestyNote: '未知即为 null，绝不猜数',
        }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/library/clips/curated' && init?.method === 'POST',
      () =>
        jsonResponse(
          { clip: { ref: 'library:c9', title: '图集', contentHtml: '<p>x</p>' }, created: true, selectedCount: 1, unknownSelections: [] },
          201,
        ),
    )
    renderWithQuery(<New311ClipTools />)
    expand(/剪藏资料工具（/, 'image-picker')
    fireEvent.change(screen.getByLabelText('页面 URL'), { target: { value: 'https://g.example/a' } })
    fireEvent.click(screen.getByRole('button', { name: '列出可用图片' }))
    await waitFor(() => expect(screen.getByText('首图')).toBeTruthy())
    expect(screen.getByText('117 KB')).toBeTruthy()
    expect(screen.getByText('体积未知')).toBeTruthy()
    fireEvent.click(screen.getByLabelText('选择图片：首图'))
    fireEvent.click(screen.getByRole('button', { name: '保存勾选的图片（1）' }))
    await waitFor(() => expect(screen.getByText(/已保存剪藏（1 张图）/)).toBeTruthy())
    const init = lastCall('/api/v1/library/clips/curated')
    expect(JSON.parse(String(init.body)).selectedImages).toEqual(['https://cdn.example/a.jpg'])
  })

  it('NEW-319 重新提取：done 后显式应用，失败行如实展示', async () => {
    mockRoute(
      (url) => url === '/api/v1/library/clips/c2/reextract' && callsTo(url).every((c) => (c.init?.method ?? 'GET') === 'GET'),
      () =>
        jsonResponse({
          clipRef: 'library:c2',
          requests: [
            { id: 'rq1', status: 'done', title: '新标题', charCount: 800, error: null, applied: false },
            { id: 'rq0', status: 'failed', title: '', charCount: 0, error: '页面返回 HTTP 500。', applied: false },
          ],
        }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/library/clips/c2/reextract' && init?.method === 'POST',
      () => jsonResponse({ id: 'rq2', clipRef: 'library:c2', status: 'done', title: '更新标题', charCount: 900, error: null, requestedAt: 't', finishedAt: 't' }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/library/clips/c2/reextract/rq1/apply' && init?.method === 'POST',
      () => jsonResponse({ id: 'rq1', clipRef: 'library:c2', appliedAt: 't', note: '新版本已切到展示位' }),
    )
    renderWithQuery(<New311ClipTools />)
    expand(/剪藏资料工具（/, 'reextract')
    fireEvent.change(screen.getByLabelText('剪藏 ref（library:…）'), { target: { value: 'library:c2' } })
    await waitFor(() => expect(screen.getByText(/失败：页面返回 HTTP 500/)).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '应用新版本' }))
    await waitFor(() => expect(screen.getByText(/新版本已切到展示位/)).toBeTruthy())
    expect(lastCall('/api/v1/library/clips/c2/reextract/rq1/apply').method).toBe('POST')
  })

  it('NEW-314 快照文字检索层：构建后查找命中并给出定位锚', async () => {
    mockRoute(
      (url, init) => url === '/api/v1/library/snapshots/s1/text-layer' && init?.method === 'POST',
      () => jsonResponse({ assetRef: 'library:s1', blockCount: 4, builtAt: 't' }, 201),
    )
    mockRoute(
      (url) => url.startsWith('/api/v1/library/snapshots/s1/text-layer?'),
      () =>
        jsonResponse({
          assetRef: 'library:s1',
          query: '爬虫',
          hits: [{ seq: 1, anchor: '第一章 研究背景', text: '分布式爬虫在过去十年成为主流。' }],
          hitCount: 1,
          truncated: false,
        }),
    )
    renderWithQuery(<New311SnapshotTextTools />)
    expand(/快照文字检索（/, 'text-layer')
    fireEvent.change(screen.getByLabelText('快照 uuid'), { target: { value: 's1' } })
    fireEvent.click(screen.getByRole('button', { name: '构建文字层' }))
    await waitFor(() => expect(screen.getByText(/文字层已构建（4 块）/)).toBeTruthy())
    fireEvent.change(screen.getByLabelText('文字层搜索词'), { target: { value: '爬虫' } })
    fireEvent.click(screen.getByRole('button', { name: '查找' }))
    await waitFor(() => expect(screen.getByText(/命中 1 处/)).toBeTruthy())
    expect(screen.getByText(/\[1\] 第一章 研究背景 · 分布式爬虫/)).toBeTruthy()
    expect(
      callsTo('/api/v1/library/snapshots/s1/text-layer').some(
        (call) => call.init?.method === 'POST',
      ),
    ).toBe(true)
  })
})
