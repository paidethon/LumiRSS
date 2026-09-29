/** NEW-291..300 Web 入口测试 — 邮件资料工具组合的渲染与交互主路径。
 *
 * 环境：jsdom；fetch 按 URL 匹配 mock（服务真源在 BFF，后端口径见
 * tests/test_new29*.py、test_new300*.py）。 */

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { New291EmailTools } from '../components/new291/New291EmailTools'

const MID = 'eml-test-1'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
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

function mockMaterialList(subject = '样本'): void {
  mockRoute(
    (url) => url === '/api/v1/email-materials' && (!init()?.method || init()?.method === 'GET'),
    () =>
      jsonResponse({
        items: [
          {
            id: MID, messageId: '', subject, fromName: '', fromAddr: 'a@b.c',
            to: '', date: '', snippet: '', sourceLabel: '', threadId: '', linkMode: 'none',
            tags: [], attachments: [], rawBytes: 0, createdAt: '',
          },
        ],
        total: 1,
      }),
  )
}

function init(): RequestInit | undefined {
  return fetchCalls.at(-1)?.init
}

function lastCall(url: string): RequestInit {
  const call = fetchCalls.filter((c) => c.url === url).at(-1)
  expect(call, `expected a fetch call to ${url}`).toBeDefined()
  return call?.init ?? {}
}

/** 展开组合 + 指定子工具（两级情境展开）。 */
function expand(subsectionId: string): void {
  fireEvent.click(screen.getByRole('button', { name: /邮件资料工具（/ }))
  const toggles = screen
    .getAllByRole('button')
    .filter((button) => {
      const host = button.closest('[data-new291-subsection]')
      return host !== null && host.getAttribute('data-new291-subsection') === subsectionId
    })
  expect(toggles.length).toBeGreaterThan(0)
  fireEvent.click(toggles[0])
}

/** 渲染 + 导入清单选中样本条目（驱动依赖 materialId 的子工具）。 */
async function renderWithSelected(): Promise<void> {
  mockMaterialList()
  render(<New291EmailTools />)
  expand('email-import')
  await waitFor(() => expect(screen.getByText(/样本 — a@b\.c/)).toBeTruthy())
  fireEvent.click(screen.getByText(/样本 — a@b\.c/))
  await waitFor(() => expect(screen.getByText(new RegExp(`当前选中条目：${MID}`))).toBeTruthy())
}

beforeEach(() => {
  fetchCalls.length = 0
  routes = []
  globalThis.fetch = (async (input: RequestInfo | URL, initArg?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    fetchCalls.push({ url, init: initArg })
    for (const route of routes) {
      if (route.match(url, initArg)) return route.respond(url, initArg)
    }
    return jsonResponse({ error: { type: 'unmocked', message: url } }, 404)
  }) as typeof fetch
})

afterEach(() => {
  cleanup()
  routes = []
})

describe('NEW-291..300 邮件资料工具（New291EmailTools）', () => {
  it('折叠态零请求；组合展开仍零查询（两级情境展开）', () => {
    render(<New291EmailTools />)
    const toggle = screen.getByRole('button', { name: /邮件资料工具（/ })
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(fetchCalls).toHaveLength(0)
    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    expect(fetchCalls).toHaveLength(0)
    expect(screen.getByText('NEW-294 订阅来源映射（地址 → 个人来源）')).toBeTruthy()
  })

  it('NEW-291 导入：选文件后 POST import；清单可选中驱动其他工具', async () => {
    const emlContent = new File(
      ['Message-ID: <x@y>\r\nFrom: a@b.c\r\nSubject: 测试\r\n\r\n正文'],
      'x.eml',
      { type: 'message/rfc822' },
    )
    mockMaterialList('测试')
    mockRoute(
      (url) => url === '/api/v1/email-materials/import',
      () =>
        jsonResponse({
          imported: [
            {
              id: MID, filename: 'x.eml', subject: '测试', fromAddr: 'a@b.c', snippet: '正文',
              tags: [], sourceLabel: '', attachments: [], messageId: 'x@y',
            },
          ],
          failed: [],
          skipped: [],
          conflicts: [],
          honestyNote: '只解析入库，不发送。',
        }),
    )
    render(<New291EmailTools />)
    expand('email-import')
    const input = screen.getByLabelText(/选择邮件文件/) as HTMLInputElement
    await waitFor(() => expect(screen.getByText('已导入 0 封')).toBeTruthy())
    fireEvent.change(input, { target: { files: [emlContent] } })
    fireEvent.click(screen.getByText('导入为资料条目'))
    await waitFor(() => expect(screen.getByText(/导入成功 1 封/)).toBeTruthy())
    expect(lastCall('/api/v1/email-materials/import').method).toBe('POST')
    expect(screen.getByText(/只解析入库，不发送/)).toBeTruthy()
    fireEvent.click(screen.getByText(/测试 — a@b\.c/))
    expect(screen.getByText(new RegExp(`当前选中条目：${MID}`))).toBeTruthy()
  })

  it('NEW-292/293：手动关联 POST thread-link；引用段折叠可展开并标核对', async () => {
    mockRoute(
      (url) => url === `/api/v1/email-materials/${MID}/thread-link`,
      () =>
        jsonResponse({
          threadId: 'eth-1',
          subjectHint: '测试',
          members: [
            { id: MID, subject: '测试', fromAddr: 'a@b.c', date: '', snippet: '', linkMode: 'manual' },
            { id: 'eml-2', subject: '回复', fromAddr: 'd@e.f', date: '', snippet: '', linkMode: 'references' },
          ],
          honestyNote: '自动串联只依据真实头部字段；按导入先后排序。',
        }),
    )
    const segments = (reviewed: boolean) => ({
      materialId: MID,
      segments: [
        { index: 0, kind: 'own', lines: 1, text: '我的新回复', reviewed: false },
        { index: 1, kind: 'quoted', lines: 2, text: '> 旧引用', reviewed },
      ],
      quotedCount: 1,
      quotedLines: 2,
      reviewedCount: reviewed ? 1 : 0,
      honestyNote: '分段按行前缀启发式识别引用。',
    })
    mockRoute(
      (url) => url === `/api/v1/email-materials/${MID}/quote-segments`,
      () => jsonResponse(segments(false)),
    )
    mockRoute(
      (url) => url === `/api/v1/email-materials/${MID}/quote-reviews`,
      () => jsonResponse(segments(true)),
    )
    await renderWithSelected()
    fireEvent.click(screen.getByText(/NEW-292 会话串联/))
    fireEvent.change(screen.getByLabelText('关联到的目标条目 ID（字段不足时的手动兜底）'), {
      target: { value: 'eml-2' },
    })
    fireEvent.click(screen.getByText('手动关联成会话'))
    await waitFor(() => expect(screen.getByText(/会话 eth-1：2 封/)).toBeTruthy())
    expect(screen.getByText(/按头部字段/)).toBeTruthy()
    expect(lastCall(`/api/v1/email-materials/${MID}/thread-link`).method).toBe('POST')

    fireEvent.click(screen.getByText(/NEW-293 引用折叠/))
    await waitFor(() => expect(screen.getByText('引用段 2（2 行）')).toBeTruthy())
    // 引用段默认折叠：旧引用文本不可见
    expect(screen.queryByText('> 旧引用')).toBeNull()
    fireEvent.click(screen.getByText('引用段 2（2 行）'))
    expect(screen.getByText('> 旧引用')).toBeTruthy()
    fireEvent.click(screen.getByText('标为已核对'))
    await waitFor(() => expect(screen.getByText('已核对')).toBeTruthy())
    expect(lastCall(`/api/v1/email-materials/${MID}/quote-reviews`).method).toBe('POST')
  })

  it('NEW-294/295：来源映射保存 PUT；遮罩添加后分享视图展示占位符', async () => {
    mockRoute(
      (url, initArg) => url === '/api/v1/email-source-maps' && (!initArg?.method || initArg.method === 'GET'),
      () => jsonResponse({ items: [] }),
    )
    mockRoute(
      (url, initArg) => url === '/api/v1/email-source-maps/news%40corp.example' && initArg?.method === 'PUT',
      () => jsonResponse({ fromAddr: 'news@corp.example', sourceLabel: '订阅通讯' }),
    )
    mockRoute(
      (url) => url === `/api/v1/email-materials/${MID}/share-view`,
      () =>
        jsonResponse({
          materialId: MID,
          maskedBodyText: '写給 [已隐藏·地址] 的邮件',
          masks: [{ id: 'emk-1', kind: 'address', kindLabel: '地址' }],
          originalPrivate: true,
          honestyNote: '原文始终私有保存。',
        }),
    )
    mockRoute(
      (url) => url === `/api/v1/email-materials/${MID}/masks`,
      () => jsonResponse({ id: 'emk-1' }, 201),
    )
    mockMaterialList()
    render(<New291EmailTools />)
    expand('email-source-maps')
    fireEvent.change(screen.getByLabelText('发件地址（精确匹配，大小写不敏感）'), {
      target: { value: 'news@corp.example' },
    })
    fireEvent.change(screen.getByLabelText('个人资料来源名称'), { target: { value: '订阅通讯' } })
    fireEvent.click(screen.getByText('保存映射'))
    await waitFor(() => {
      expect(lastCall('/api/v1/email-source-maps/news%40corp.example').method).toBe('PUT')
      expect(JSON.parse(String(lastCall('/api/v1/email-source-maps/news%40corp.example').body))).toMatchObject({
        sourceLabel: '订阅通讯',
      })
    })

    // 选中条目后展开遮罩子工具（组合已展开，直接点子区标题）
    fireEvent.click(screen.getByText(/NEW-291 导入 EML/))
    await waitFor(() => expect(screen.getByText(/样本 — a@b\.c/)).toBeTruthy())
    fireEvent.click(screen.getByText(/样本 — a@b\.c/))
    fireEvent.click(screen.getByText(/NEW-295 隐私遮罩/))
    await waitFor(() => expect(screen.getByLabelText('遮罩类型')).toBeTruthy())
    fireEvent.change(screen.getByLabelText('要隐藏的字面文本（必须出现在正文中）'), {
      target: { value: 'a@b.c' },
    })
    fireEvent.click(screen.getByText('添加遮罩（分享时隐藏）'))
    await waitFor(() => expect(screen.getByText(/分享视图（原文仍私有保存/)).toBeTruthy())
    expect(screen.getByText((_, el) => el?.textContent === '写給 [已隐藏·地址] 的邮件')).toBeTruthy()
    expect(screen.getByText(/原文始终私有保存/)).toBeTruthy()
  })

  it('NEW-298/299：冲突三种择留；退订卡只展示 + 记录主动打开', async () => {
    mockRoute(
      (url, initArg) => url === '/api/v1/email-duplicates' && (!initArg?.method || initArg.method === 'GET'),
      () =>
        jsonResponse({
          items: [
            {
              id: 'edc-1', messageId: 'dup@x', existingId: 'eml-a', digestsDiffer: true,
              filename: 'dup.eml', status: 'pending', resultId: '',
              incomingPreview: { subject: '改过的版本', fromAddr: 'a@b.c', snippet: '不一样', attachmentCount: 0 },
            },
          ],
        }),
    )
    mockRoute(
      (url) => url === '/api/v1/email-duplicates/edc-1/resolve',
      () => jsonResponse({ id: 'edc-1', choice: 'keep_both', status: 'kept_both', resultId: 'eml-new' }),
    )
    mockRoute(
      (url) => url === `/api/v1/email-materials/${MID}/unsubscribe`,
      () =>
        jsonResponse({
          materialId: MID,
          available: true,
          methods: [{ type: 'http', target: 'https://corp.example/unsub' }],
          oneClickDeclared: true,
          listHelp: '',
          opens: [],
          honestyNote: '只展示，绝不自动执行退订请求。',
        }),
    )
    mockRoute(
      (url) => url === `/api/v1/email-materials/${MID}/unsubscribe-open`,
      () => jsonResponse({ note: '已记录你主动打开。' }, 201),
    )
    mockMaterialList()
    render(<New291EmailTools />)
    expand('email-duplicates')
    await waitFor(() => expect(screen.getByText(/待复核冲突 1 条/)).toBeTruthy())
    fireEvent.click(screen.getByText('两个都留'))
    await waitFor(() => expect(lastCall('/api/v1/email-duplicates/edc-1/resolve').method).toBe('POST'))
    expect(JSON.parse(String(lastCall('/api/v1/email-duplicates/edc-1/resolve').body))).toMatchObject({
      choice: 'keep_both',
    })

    // 组合已展开，直接点子区标题展开导入清单并选中
    fireEvent.click(screen.getByText(/NEW-291 导入 EML/))
    await waitFor(() => expect(screen.getByText(/样本 — a@b\.c/)).toBeTruthy())
    fireEvent.click(screen.getByText(/样本 — a@b\.c/))
    fireEvent.click(screen.getByText(/NEW-299 退订信息卡/))
    await waitFor(() => expect(screen.getByText('https://corp.example/unsub')).toBeTruthy())
    expect(screen.getByText(/原文声明支持 One-Click/)).toBeTruthy()
    fireEvent.click(screen.getByText('记录我主动打开'))
    await waitFor(() => expect(screen.getByText('已记录你主动打开。')).toBeTruthy())
    expect(lastCall(`/api/v1/email-materials/${MID}/unsubscribe-open`).method).toBe('POST')
  })

  it('NEW-300 脱敏导出：默认未勾选 → options 全 false + 删除清单渲染', async () => {
    mockRoute(
      (url, initArg) => url === `/api/v1/email-materials/${MID}/export` && initArg?.method === 'POST',
      () =>
        jsonResponse({
          exportId: 'eex-1',
          options: { includeAddresses: false, includeFullHeaders: false },
          subject: '样本', from: '', to: '', headers: {}, bodyText: '正文',
          attachments: [], maskedRegions: [],
          removedFields: [{ field: 'from', reason: '未勾选保留地址：发件人姓名与地址已删除。' }],
          honestyNote: '默认脱敏。',
        }),
    )
    await renderWithSelected()
    fireEvent.click(screen.getByText(/NEW-300 脱敏导出/))
    fireEvent.click(screen.getByText('生成导出（默认脱敏）'))
    await waitFor(() => expect(screen.getByText(/删除字段 1 项/)).toBeTruthy())
    const body = JSON.parse(String(lastCall(`/api/v1/email-materials/${MID}/export`).body))
    expect(body).toMatchObject({ includeAddresses: false, includeFullHeaders: false })
    expect(screen.getByText(/未勾选保留地址/)).toBeTruthy()
    expect(screen.getByText(/默认脱敏。/)).toBeTruthy()
  })
})
