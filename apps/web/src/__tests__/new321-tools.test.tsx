/** NEW-321..330 Web 入口测试 — Obsidian 互通工具组的渲染与交互主路径。
 *
 * 环境：jsdom；fetch 按 URL 匹配 mock（服务真源在 BFF，后端口径见
 * tests/test_new32*.py / test_new330*.py）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { New321InterconnectTools } from '../components/new321/New321InterconnectTools'

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

function lastCall(url: string): RequestInit {
  const calls = fetchCalls.filter(
    (call) => call.url === url || call.url.startsWith(`${url}?`),
  )
  expect(calls.length, `expected a fetch call to ${url}`).toBeGreaterThan(0)
  return calls[calls.length - 1]?.init ?? {}
}

/** 展开组合面板 + 指定子工具（两级情境展开）。 */
function expand(mainName: RegExp, subsectionId: string): void {
  fireEvent.click(screen.getByRole('button', { name: mainName }))
  const toggles = screen.getAllByRole('button').filter((button) => {
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

describe('NEW-321..330 Obsidian 互通工具组', () => {
  it('折叠态零请求；aria-expanded 随开关翻转（情境展开）', () => {
    renderWithQuery(<New321InterconnectTools />)
    const toggle = screen.getByRole('button', { name: /Obsidian 互通工具（/ })
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(fetchCalls).toHaveLength(0)
    fireEvent.click(toggle)
    expect(screen.getByRole('button', { name: /Obsidian 互通工具（/ }).getAttribute('aria-expanded')).toBe('true')
    // 展开后子区仍是折叠的（二级情境展开 → 依旧零查询）
    expect(fetchCalls.map((c) => `${c.init?.method ?? 'GET'} ${c.url}`)).toEqual([])
  })

  it('NEW-321 标签映射：预览层级与冲突可见；保存规则 PUT 后刷新', async () => {
    mockRoute(
      (url) => url === '/api/v1/obsidian/tag-mapping/preview',
      () =>
        jsonResponse({
          sourceTags: ['ai', 'tech'],
          mappings: [
            { sourceTag: 'ai', targetTag: 'tech/人工智能', mapped: true },
            { sourceTag: 'tech', targetTag: 'tech', mapped: false },
          ],
          hierarchy: { ai: ['tech'] },
          conflicts: [{ sourceTag: 'ml', kind: 'target_is_source_tag', detail: '目标 tech 本身也是源标签。' }],
          merges: [],
        }),
    )
    mockRoute(
      (url) => url === '/api/v1/obsidian/tag-mapping/rules',
      (url, init) =>
        init?.method === 'PUT'
          ? jsonResponse({ sourceTag: 'ai', targetTag: 'tech/人工智能' })
          : jsonResponse({ rules: [{ sourceTag: 'ai', targetTag: 'tech/人工智能' }] }),
    )
    renderWithQuery(<New321InterconnectTools />)
    expand(/Obsidian 互通工具（/, 'tag-mapping')
    await waitFor(() =>
      expect(screen.getByText(/冲突 1 条/)).toBeTruthy(),
    )
    expect(screen.getByText(/#ai → #tech\/人工智能/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText('源标签'), { target: { value: '深度学习' } })
    fireEvent.change(screen.getByLabelText('个人标签（可用 / 分层级）'), {
      target: { value: 'tech/深度学习' },
    })
    fireEvent.click(screen.getByRole('button', { name: '保存规则' }))
    await waitFor(() => expect(screen.getByText('规则已保存。')).toBeTruthy())
    const putCall = fetchCalls.find(
      (call) => call.url === '/api/v1/obsidian/tag-mapping/rules' && call.init?.method === 'PUT',
    )
    expect(putCall, 'expected a PUT call to rules').toBeTruthy()
    expect(putCall?.init?.method).toBe('PUT')
    expect(JSON.parse(String(putCall?.init?.body))).toEqual({
      sourceTag: '深度学习',
      targetTag: 'tech/深度学习',
    })
  })

  it('NEW-323 同步审批：预览清单 → 确认后 apply 携带审批 id', async () => {
    mockRoute(
      (url) => url === '/api/v1/obsidian/sync/preview',
      () =>
        jsonResponse({
          id: 'approval-1',
          status: 'pending',
          added: 2,
          changed: 1,
          removed: 0,
          renames: 0,
          files: { added: { items: ['a.md', 'b.md'] }, changed: { items: ['c.md'] }, removed: { items: [] } },
        }),
    )
    mockRoute(
      (url) => url === '/api/v1/obsidian/sync/apply',
      () =>
        jsonResponse({
          id: 'approval-1',
          status: 'applied',
          report: { added: 2, changed: 1, removed: 0 },
        }),
    )
    mockRoute(
      (url) => url === '/api/v1/obsidian/sync/approvals',
      () => jsonResponse({ approvals: [] }),
    )
    renderWithQuery(<New321InterconnectTools />)
    expand(/Obsidian 互通工具（/, 'sync-approval')
    fireEvent.click(screen.getByRole('button', { name: '预览同步差异' }))
    await waitFor(() =>
      expect(screen.getByText(/新增 2 · 修改 1 · 删除 0/)).toBeTruthy(),
    )
    expect(screen.getByText('新增：a.md')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '确认同步（更新镜像）' }))
    await waitFor(() =>
      expect(screen.getByText(/镜像已更新：新增 2 · 修改 1 · 删除 0/)).toBeTruthy(),
    )
    const init = lastCall('/api/v1/obsidian/sync/apply')
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ approvalId: 'approval-1' })
  })

  it('NEW-324 批注 Markdown 输出：生成内容与诚实保存提示', async () => {
    mockRoute(
      (url) => url === '/api/v1/annotations/markdown-export',
      (url, init) => {
        if (init?.method === 'POST') {
          return jsonResponse({
            id: 'exp1',
            filename: 'LumiRSS-批注-20260929-1200.md',
            content: '# LumiRSS 阅读批注导出\n^lumi-para-1',
            entryCount: 1,
            annotationCount: 2,
            unresolvedRefs: [],
            honestyNote: '请自行保存。',
          })
        }
        return jsonResponse({ exports: [] })
      },
    )
    renderWithQuery(<New321InterconnectTools />)
    expand(/Obsidian 互通工具（/, 'annotation-export')
    fireEvent.change(screen.getByLabelText('文章 ref（每行一个，如 rss:…）'), {
      target: { value: 'rss:e1\n' },
    })
    fireEvent.click(screen.getByRole('button', { name: '生成 Markdown（1 篇）' }))
    await waitFor(() =>
      expect(screen.getByText(/已生成 LumiRSS-批注-20260929-1200.md（2 条批注）/)).toBeTruthy(),
    )
    const init = lastCall('/api/v1/annotations/markdown-export')
    expect(JSON.parse(String(init.body))).toEqual({ entryRefs: ['rss:e1'] })
    expect(
      (screen.getByLabelText('批注 Markdown 内容') as HTMLTextAreaElement).value,
    ).toContain('^lumi-para-1')
  })

  it('NEW-325/329 多根档案：建立 → 扫描 → 断开后扫描按钮禁用 + 副本二选一', async () => {
    let rootState = {
      id: 'root-1',
      label: '研究库',
      rootPath: '/data/vault',
      ignoreGlobs: [],
      authorized: true,
      copiesPolicy: '',
      lastScanAt: null,
      lastError: null,
      noteCount: 2,
    }
    mockRoute(
      (url) => url === '/api/v1/obsidian/roots' && !url.includes('/scan'),
      (url, init) => {
        if (init?.method === 'POST') {
          rootState = { ...rootState, label: '新库' }
          return jsonResponse({ ...rootState, label: '新库' }, 201)
        }
        return jsonResponse({ roots: [rootState] })
      },
    )
    mockRoute(
      (url) => url === '/api/v1/obsidian/roots/root-1/scan',
      () => jsonResponse({ added: 2, changed: 0, removed: 0, unchanged: 0 }),
    )
    mockRoute(
      (url) => url === '/api/v1/obsidian/roots/root-1/disconnect',
      () => {
        rootState = { ...rootState, authorized: false }
        return jsonResponse(rootState)
      },
    )
    mockRoute(
      (url) => url === '/api/v1/obsidian/roots/root-1/copies',
      () => jsonResponse({ copiesPolicy: 'deleted', removedCopies: 2 }),
    )
    mockRoute(
      (url) => url === '/api/v1/obsidian/roots/root-1/notes',
      () => jsonResponse({ notes: [{ id: 'n1', relPath: 'a.md', title: 'A', tags: [] }] }),
    )
    renderWithQuery(<New321InterconnectTools />)
    expand(/Obsidian 互通工具（/, 'root-profiles')
    await waitFor(() => expect(screen.getByText('研究库')).toBeTruthy())
    expect(screen.getByText(/2 条 · 已授权/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '查看笔记' }))
    await waitFor(() => expect(screen.getByText('a.md')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '断开连接' }))
    await waitFor(() => expect(screen.getByText(/已断开：扫描停止/)).toBeTruthy())
    await waitFor(() =>
      expect(screen.getByText(/2 条 · 已断开/)).toBeTruthy(),
    )
    // 断开后：扫描按钮禁用（扫描入口被拒），副本二选一按钮出现
    expect(screen.getByRole('button', { name: '扫描' }).hasAttribute('disabled')).toBe(true)
    expect(screen.getByRole('button', { name: '删除副本' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '删除副本' }))
    await waitFor(() =>
      expect(screen.getByText(/本应用副本已删除（源目录未动）/)).toBeTruthy(),
    )
    const init = lastCall('/api/v1/obsidian/roots/root-1/copies')
    expect(JSON.parse(String(init.body))).toEqual({ action: 'delete' })
  })

  it('NEW-328 冲突收件箱：并排展示 + 显式二选一解决', async () => {
    mockRoute(
      (url) => url === '/api/v1/obsidian/conflict-inbox/detect',
      () => jsonResponse({ checked: 1, opened: 1, refreshed: 0, unchanged: 0, honestyNote: 'x' }),
    )
    let resolved = false
    mockRoute(
      (url) => url === '/api/v1/obsidian/conflict-inbox' && !url.includes('detect') && !url.includes('corrections'),
      () =>
        jsonResponse({
          conflicts: resolved
            ? []
            : [
                {
                  id: 'cf-1',
                  source: { title: '源更新后的标题', excerpt: '第二版正文' },
                  personal: { title: '我的标题', note: '' },
                  status: 'open',
                },
              ],
        }),
    )
    mockRoute(
      (url) => url === '/api/v1/obsidian/conflict-inbox/cf-1/resolve',
      () => {
        resolved = true
        return jsonResponse({ id: 'cf-1', status: 'kept_independent' })
      },
    )
    mockRoute(
      (url) => url === '/api/v1/obsidian/conflict-inbox/corrections',
      () => jsonResponse({ corrections: [] }),
    )
    renderWithQuery(<New321InterconnectTools />)
    expand(/Obsidian 互通工具（/, 'conflict-inbox')
    await waitFor(() => expect(screen.getByText('源更新后的标题')).toBeTruthy())
    expect(screen.getByText('我的标题')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '保留独立层' }))
    await waitFor(() =>
      expect(screen.getByText(/已保留独立层（修正重定基到新版本）/)).toBeTruthy(),
    )
    const init = lastCall('/api/v1/obsidian/conflict-inbox/cf-1/resolve')
    expect(JSON.parse(String(init.body))).toEqual({ decision: 'keep_independent' })
  })

  it('NEW-330 重定位向导：预览按校验和匹配 → 应用不重复导入', async () => {
    mockRoute(
      (url) => url === '/api/v1/obsidian/roots' && !url.includes('relocate'),
      () =>
        jsonResponse({
          roots: [
            {
              id: 'root-1',
              label: '移动过的库',
              rootPath: '/old',
              ignoreGlobs: [],
              authorized: true,
              copiesPolicy: '',
              lastScanAt: null,
              lastError: null,
              noteCount: 2,
            },
          ],
        }),
    )
    mockRoute(
      (url) => url === '/api/v1/obsidian/roots/root-1/relocate/preview',
      () =>
        jsonResponse({
          id: 'rel-1',
          status: 'previewed',
          newPath: '/new',
          counts: { relocated: 2, fresh: 1, changed: 0, vanished: 0, ambiguous: 0, collision: 0 },
          relocated: [
            { from: 'a.md', to: 'notes/a.md' },
            { from: 'b.md', to: 'notes/b.md' },
          ],
        }),
    )
    mockRoute(
      (url) => url === '/api/v1/obsidian/roots/root-1/relocate/rel-1/apply',
      () => jsonResponse({ relocatedApplied: 2 }),
    )
    renderWithQuery(<New321InterconnectTools />)
    expand(/Obsidian 互通工具（/, 'relocation')
    await waitFor(() => screen.getByLabelText('重定位的资料根档案'))
    fireEvent.change(screen.getByLabelText('重定位的资料根档案'), {
      target: { value: 'root-1' },
    })
    fireEvent.change(screen.getByLabelText('重定位新根路径'), {
      target: { value: '/new' },
    })
    fireEvent.click(screen.getByRole('button', { name: '预览匹配' }))
    await waitFor(() =>
      expect(screen.getByText(/重定位 2 · 同路径内容已变 0 · 新增 1/)).toBeTruthy(),
    )
    expect(screen.getByText('a.md → notes/a.md')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '应用重定位' }))
    await waitFor(() =>
      expect(screen.getByText(/已接续 2 条档案（行身份不变，未重复导入）/)).toBeTruthy(),
    )
    expect(lastCall('/api/v1/obsidian/roots/root-1/relocate/rel-1/apply').method).toBe('POST')
  })
})
