/** NEW-231..240 Web 入口测试 — 标注侧/笔记侧工具组合的渲染与交互主路径。
 *
 * 环境：jsdom；fetch 按 URL 匹配 mock（服务真源在 BFF，后端口径见
 * tests/test_new23*.py）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { New231AnnotationTools } from '../components/new231/New231AnnotationTools'
import { New231NoteTools } from '../components/new231/New231NoteTools'

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
let routes: { match: (url: string, init?: RequestInit) => boolean; respond: (url: string, init?: RequestInit) => Response }[] = []

function mockRoute(
  matcher: (url: string, init?: RequestInit) => boolean,
  responder: (url: string, init?: RequestInit) => Response,
): void {
  routes.push({ match: matcher, respond: responder })
}

beforeEach(() => {
  fetchCalls.length = 0
  routes = []
  // 单一持久 wrapper：每个测试自带全新路由表（无跨测试堆叠）
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

describe('NEW-231..240 标注侧工具（New231AnnotationTools）', () => {
  it('NEW-233 汇总按文章分组渲染且回原段链接携带段落定位；不渲染第二份正文', async () => {
    mockRoute(
      (url) => url.startsWith('/api/v1/annotations/summary'),
      () =>
        jsonResponse({
          entries: [
            {
              entryRef: 'e-1',
              title: '一篇文章',
              source: '某来源',
              annotationCount: 1,
              annotations: [
                {
                  id: 'a-1',
                  excerpt: '关键摘录',
                  note: '我的批注',
                  color: 'yellow',
                  paraId: 'p-3',
                  stale: false,
                  backHref: '/reader?entry=e-1&para=p-3',
                },
              ],
            },
          ],
          entryCount: 1,
          totalAnnotations: 1,
          truncated: false,
        }),
    )
    renderWithQuery(<New231AnnotationTools selectedIds={new Set()} />)
    await waitFor(() => expect(screen.getByText(/关键摘录/)).toBeTruthy())
    const back = screen.getByText('回原段').closest('a')
    expect(back?.getAttribute('href')).toBe('/reader?entry=e-1&para=p-3')
    expect(screen.queryByText('contentText')).toBeNull()
  })

  it('NEW-234 建层并把选中批注加入层（POST 到层成员端点）', async () => {
    let created = false
    mockRoute(
      (url, init) => url === '/api/v1/annotation-layers' && (!init?.method || init.method === 'GET'),
      () => jsonResponse({ items: created ? [{ id: 'L1', name: '考据层', createdAt: 't', itemCount: 1 }] : [] }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/annotation-layers' && init?.method === 'POST',
      () => {
        created = true
        return jsonResponse({ id: 'L1', name: '考据层', createdAt: 't', itemCount: 0 }, 201)
      },
    )
    mockRoute(
      (url, init) => url === '/api/v1/annotation-layers/L1/items' && init?.method === 'POST',
      () => jsonResponse({ added: ['a-1'], skipped: [] }),
    )
    renderWithQuery(<New231AnnotationTools selectedIds={new Set(['a-1'])} />)
    const nameInput = await screen.findByLabelText('新层名称')
    fireEvent.change(nameInput, { target: { value: '考据层' } })
    fireEvent.click(screen.getByText('创建层'))
    await waitFor(() => expect(screen.getByText(/考据层/)).toBeTruthy())
    fireEvent.click(screen.getByText(/选中批注加入层/))
    await waitFor(() => expect(screen.getByText('已加入 1 条。')).toBeTruthy())
    const call = fetchCalls.find((c) => c.url === '/api/v1/annotation-layers/L1/items')
    expect(call?.init?.method).toBe('POST')
    expect(JSON.parse(String(call?.init?.body))).toEqual({ annotationIds: ['a-1'] })
  })

  it('NEW-238 迁移先预览（零写入）再应用；正文与文章身份不在请求里', async () => {
    mockRoute(
      (url, init) => url === '/api/v1/annotation-layers' && (!init?.method || init.method === 'GET'),
      () =>
        jsonResponse({
          items: [
            { id: 'L1', name: '考据层', createdAt: 't', itemCount: 1 },
            { id: 'L2', name: '待办层', createdAt: 't', itemCount: 0 },
          ],
        }),
    )
    mockRoute(
      (url) => url === '/api/v1/annotation-layers/migrate/preview',
      () =>
        jsonResponse({
          fromLayerId: 'L1',
          toLayerId: 'L2',
          fromLayer: '考据层',
          toLayer: '待办层',
          items: [
            { annotationId: 'a-1', entryRef: 'e-1', excerpt: '要迁的摘录', color: 'yellow', fromLayer: '考据层', toLayer: '待办层' },
          ],
          count: 1,
        }),
    )
    mockRoute(
      (url) => url === '/api/v1/annotation-layers/migrate/apply',
      () => jsonResponse({ moved: ['a-1'], skipped: [], count: 1 }),
    )
    renderWithQuery(<New231AnnotationTools selectedIds={new Set(['a-1'])} />)
    const fromSelect = await screen.findByLabelText('来源层')
    const toSelect = screen.getByLabelText('目标层')
    await screen.findAllByText('待办层') // 等层列表渲染出 option（来源/目标两处）再切换
    fireEvent.change(fromSelect, { target: { value: 'L1' } })
    fireEvent.change(toSelect, { target: { value: 'L2' } })
    fireEvent.click(screen.getByText('预览迁移'))
    await waitFor(() => expect(screen.getByText(/预览，未写入/)).toBeTruthy())
    expect(screen.getByText(/要迁的摘录/)).toBeTruthy()
    fireEvent.click(screen.getByText('确认迁移'))
    await waitFor(() => expect(screen.getByText(/已迁移 1 条；原文章身份未改动。/)).toBeTruthy())
    const previewCall = fetchCalls.find((c) => c.url === '/api/v1/annotation-layers/migrate/preview')
    const applyCall = fetchCalls.find((c) => c.url === '/api/v1/annotation-layers/migrate/apply')
    expect(JSON.parse(String(previewCall?.init?.body))).toEqual({ fromLayerId: 'L1', toLayerId: 'L2', annotationIds: ['a-1'] })
    expect(JSON.parse(String(applyCall?.init?.body))).toEqual({ fromLayerId: 'L1', toLayerId: 'L2', annotationIds: ['a-1'] })
  })

  it('NEW-237 预览卡片展示 markdown 与来源索引；未知 id 诚实上报', async () => {
    mockRoute(
      (url) => url === '/api/v1/annotation-cards/preview',
      () =>
        jsonResponse({
          title: '引用卡片',
          markdown: '# 引用卡片\n\n> 第一段引文 [1]',
          sources: [{ index: 1, entryRef: 'e-1', title: 'T', source: 'S', date: '2026-01-01', backHref: '/reader?entry=e-1' }],
          quoteCount: 1,
          unknownIds: ['ghost'],
        }),
    )
    renderWithQuery(<New231AnnotationTools selectedIds={new Set(['a-1', 'ghost'])} />)
    fireEvent.click(await screen.findByText('预览卡片（2 条）'))
    await waitFor(() => expect(screen.getByText(/第一段引文/)).toBeTruthy())
    expect(screen.getByText(/有 1 条无法引用/)).toBeTruthy()
    expect(screen.getByText(/来源索引 1 项/)).toBeTruthy()
  })

  it('NEW-236 收件人可关闭提醒串；关闭后从默认收件箱消失', async () => {
    let dismissed = false
    mockRoute(
      (url, init) => url.startsWith('/api/v1/annotation-replies') && url !== '/api/v1/annotation-replies/th-1/dismiss' && (!init?.method || init.method === 'GET'),
      () =>
        jsonResponse({
          items: dismissed
            ? []
            : [
                {
                  id: 'th-1',
                  annotationId: 'a-9',
                  entryRef: 'e-9',
                  excerpt: '共享摘录',
                  note: 'owner 批注',
                  sharedWithUsername: 'me',
                  createdAt: 't0',
                  updatedAt: 't1',
                  dismissedAt: null,
                  unreadForRecipient: 2,
                  replyCount: 1,
                },
              ],
        }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/annotation-replies/th-1/dismiss' && init?.method === 'POST',
      () => {
        dismissed = true
        return new Response(null, { status: 204 })
      },
    )
    renderWithQuery(<New231AnnotationTools selectedIds={new Set()} />)
    await waitFor(() => expect(screen.getByText(/【2 条未读】/)).toBeTruthy())
    fireEvent.click(screen.getByText('关闭提醒'))
    await waitFor(() => expect(screen.getByText('已关闭该串提醒。')).toBeTruthy())
    expect(fetchCalls.some((c) => c.url === '/api/v1/annotation-replies/th-1/dismiss')).toBe(true)
  })

  it('NEW-232 为首个选中标注重锚并展示历史（旧位置保留）', async () => {
    mockRoute(
      (url) => url === '/api/v1/annotations/a-1/re-anchor-history',
      () =>
        jsonResponse({
          annotationId: 'a-1',
          items: [
            {
              id: 'h-1',
              oldAnchor: { paraId: 'block-0' },
              oldExcerpt: '旧摘录文本',
              newAnchor: { paraId: 'block-7' },
              newExcerpt: '旧摘录文本',
              source: 'manual',
              reanchoredAt: '2026-01-01T00:00:00',
            },
          ],
        }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/annotations/a-1/re-anchor' && init?.method === 'POST',
      () => jsonResponse({ id: 'a-1', anchor: { paraId: 'block-9' }, excerpt: '旧摘录文本' }),
    )
    renderWithQuery(<New231AnnotationTools selectedIds={new Set(['a-1'])} />)
    const paraInput = await screen.findByLabelText('新段落定位')
    fireEvent.change(paraInput, { target: { value: 'block-9' } })
    fireEvent.click(screen.getByText('重锚到此段'))
    await waitFor(() => expect(screen.getByText(/旧引文与旧位置已永久保留/)).toBeTruthy())
    await waitFor(() => expect(screen.getByText(/旧引文「旧摘录文本…」已保留/)).toBeTruthy())
  })
})

describe('NEW-231..240 笔记侧工具（New231NoteTools）', () => {
  it('未选中笔记时诚实空态', () => {
    renderWithQuery(<New231NoteTools noteId={null} />)
    expect(screen.getByText(/笔记工具/)).toBeTruthy()
  })

  it('NEW-231 快照 → diff → 恢复（恢复记录可见）', async () => {
    const state = { snapshotted: false }
    mockRoute(
      (url, init) =>
        url === '/api/v1/library/notes/n-1/versions' && (!init?.method || init.method === 'GET'),
      () =>
        jsonResponse(
          state.snapshotted
            ? {
                noteId: 'n-1',
                current: { ref: 'current', title: 'T', updatedAt: 't' },
                items: [{ id: 'v-1', title: 'T', origin: 'manual', createdAt: 't0' }],
              }
            : { noteId: 'n-1', current: { ref: 'current', title: 'T', updatedAt: 't' }, items: [] },
        ),
    )
    mockRoute(
      (url, init) => url === '/api/v1/library/notes/n-1/versions' && init?.method === 'POST',
      () => {
        state.snapshotted = true
        return jsonResponse({ id: 'v-1', origin: 'manual', noteId: 'n-1', title: 'T', createdAt: 't0' }, 201)
      },
    )
    mockRoute(
      (url) => url === '/api/v1/library/notes/n-1/versions/diff?fromVersion=v-1',
      () => jsonResponse({ noteId: 'n-1', fromVersion: 'v-1', toVersion: 'current', unified: '---\n+++', addedLines: 2, removedLines: 1, identical: false }),
    )
    mockRoute(
      (url) => url === '/api/v1/library/notes/n-1/versions/restores',
      () => jsonResponse({ noteId: 'n-1', items: [{ id: 'r-1', versionId: 'v-1', versionOrigin: 'manual', restoredAt: 't2' }] }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/library/notes/n-1/versions/v-1/restore' && init?.method === 'POST',
      () => jsonResponse({ noteId: 'n-1', restoredFrom: 'v-1', preRestoreVersionId: 'v-2', restoredAt: 't2' }),
    )
    renderWithQuery(<New231NoteTools noteId="n-1" />)
    fireEvent.click(await screen.findByText('保存当前版为快照'))
    await waitFor(() => expect(screen.getByText('已保存当前版快照。')).toBeTruthy())

    const select = screen.getByLabelText('选择对比起始版本') as HTMLSelectElement
    fireEvent.change(select, { target: { value: 'v-1' } })
    fireEvent.click(screen.getByText('与当前版对比'))
    await waitFor(() => expect(screen.getByText('+2 行 / -1 行')).toBeTruthy())

    fireEvent.click(screen.getByText('恢复此版'))
    await waitFor(() => expect(screen.getByText(/恢复前内容已存为快照/)).toBeTruthy())
    expect(screen.getByText(/恢复记录：1 次/)).toBeTruthy()
  })

  it('NEW-239 并排展示两版并提供解决动作（保留对方）', async () => {
    mockRoute(
      (url) => url === '/api/v1/library/notes/n-1/conflicted-edits',
      () =>
        jsonResponse({
          server: { noteId: 'n-1', title: 'T', contentMd: '本机正文', version: 2, updatedAt: 't' },
          pending: [{ id: 'p-1', title: 'T', contentMd: '对方正文', deviceLabel: 'device-b', baseVersion: 1 }],
        }),
    )
    mockRoute(
      (url, init) =>
        url === '/api/v1/library/notes/n-1/conflicted-edits/p-1/resolve' && init?.method === 'POST',
      () => jsonResponse({ resolution: 'keep_pending', note: { noteId: 'n-1', title: 'T', contentMd: '对方正文', version: 3, updatedAt: 't' } }),
    )
    renderWithQuery(<New231NoteTools noteId="n-1" />)
    await waitFor(() => expect(screen.getByText('本机正文')).toBeTruthy())
    expect(screen.getByText('对方正文')).toBeTruthy()
    expect(screen.getByText(/device-b（基于 v1）/)).toBeTruthy()
    fireEvent.click(screen.getByText('保留对方'))
    await waitFor(() => expect(screen.getByText('冲突已解决。')).toBeTruthy())
  })

  it('NEW-240 附件清单展示容量并可移除（正文不动）', async () => {
    mockRoute(
      (url) => url === '/api/v1/library/notes/n-1/attachments',
      () =>
        jsonResponse({
          noteId: 'n-1',
          items: [{ id: 'at-1', filename: '卡片.txt', mimeType: 'text/plain', sizeBytes: 2048, createdAt: 't' }],
          usage: { count: 1, totalBytes: 2048, fileCapBytes: 262144, noteCapBytes: 1048576, fileCapCount: 10 },
        }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/library/notes/n-1/attachments/at-1' && init?.method === 'DELETE',
      () => new Response(null, { status: 204 }),
    )
    renderWithQuery(<New231NoteTools noteId="n-1" />)
    await waitFor(() => expect(screen.getByText('卡片.txt')).toBeTruthy())
    expect(screen.getByText('1/10 个 · 2.0 KB/1024.0 KB')).toBeTruthy()
    fireEvent.click(screen.getByLabelText('移除附件 卡片.txt'))
    await waitFor(() => expect(screen.getByText('附件已移除；文字笔记保留。')).toBeTruthy())
  })

  it('NEW-235 选择模板后按字段渲染填空并保存', async () => {
    mockRoute(
      (url) => url === '/api/v1/note-templates',
      () =>
        jsonResponse({
          items: [{ id: 'tpl-1', name: '阅读记录', fields: [{ key: 'key_claim', label: '核心论断' }] }],
        }),
    )
    mockRoute(
      (url) => url === '/api/v1/library/notes/n-1/template-fill',
      () => jsonResponse({ noteId: 'n-1', templateId: null, fields: [], values: {} }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/library/notes/n-1/template-fill' && init?.method === 'PUT',
      () => jsonResponse({ noteId: 'n-1', templateId: 'tpl-1', values: { key_claim: '密度随温度变化' } }),
    )
    renderWithQuery(<New231NoteTools noteId="n-1" />)
    const select = await screen.findByLabelText('选择模板')
    await screen.findByText('阅读记录') // 等模板列表渲染出 option 再切换
    fireEvent.change(select, { target: { value: 'tpl-1' } })
    const field = await screen.findByLabelText('核心论断')
    fireEvent.change(field, { target: { value: '密度随温度变化' } })
    fireEvent.click(screen.getByText('保存填充'))
    await waitFor(() => expect(screen.getByText(/自由文本区未改动/)).toBeTruthy())
    const put = fetchCalls.find((c) => c.url === '/api/v1/library/notes/n-1/template-fill' && c.init?.method === 'PUT')
    expect(JSON.parse(String(put?.init?.body))).toEqual({
      templateId: 'tpl-1',
      values: { key_claim: '密度随温度变化' },
    })
  })
})
