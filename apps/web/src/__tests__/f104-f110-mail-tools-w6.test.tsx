/** F104/F105/F106/F110 —— W6 邮件域 Web 层。
 *
 * F104：解析对照对话框（Message-ID 门 → 结构快照/统计渲染；404 诚实）；
 * F105：接收规则面板（列表/新增/启停/试跑）；F106：历史回填向导
 * （试运行 → 执行；uidvalidity 中止诚实）；F110：查看会话有序链
 * （当前标记 + 缺父降级）。fetch 全部 stub，绝不触网。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { MailSection } from '../components/settings/MailSection'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const LISTS = {
  items: [{ uuid: 'list-1', name: '新闻邮件', createdAt: '2026-09-01T00:00:00Z' }],
}

const IMAP = {
  configured: true,
  enabled: true,
  host: 'imap.example.com',
  port: 993,
  user: 'u',
  folder: 'INBOX',
  ssl: true,
  listUuid: 'list-1',
  intervalSeconds: 300,
  passwordConfigured: true,
}

function baseHandler(url: string, init?: RequestInit): Response {
  if (url.endsWith('/mail/bridge-lists')) return jsonResponse(LISTS)
  if (url.endsWith('/mail/imap/settings') && (!init?.method || init.method === 'GET')) {
    return jsonResponse(IMAP)
  }
  if (/\/mail\/lists\/list-1\/rules$/.test(url) && (!init?.method || init.method === 'GET')) {
    return jsonResponse({
      items: [
        { id: 1, listUuid: 'list-1', priority: 0, field: 'from', op: 'contains', value: 'newsletter', action: 'allow', enabled: true },
      ],
    })
  }
  throw new Error(`unexpected fetch: ${url} ${init?.method ?? 'GET'}`)
}

function renderMail(handler?: (url: string, init?: RequestInit) => Response) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) =>
    (handler ?? baseHandler)(String(input), init),
  )
  vi.stubGlobal('fetch', fetchMock)
  render(
    <QueryClientProvider client={qc}>
      <MailSection />
    </QueryClientProvider>,
  )
  return fetchMock
}

function qs(attr: string): HTMLElement {
  const el = document.querySelector(`[${attr}]`)
  if (el === null) throw new Error(`missing ${attr}`)
  return el as HTMLElement
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F104 解析对照对话框', () => {
  it('F104: Message-ID 门 → 结构快照树与统计渲染', async () => {
    renderMail((url, init) => {
      if (/\/mail\/lists\/list-1\/messages\/m1%40example.com\/parse-debug/.test(url)) {
        return jsonResponse({
          messageId: 'm1@example.com',
          structure: { type: 'multipart/alternative', parts: [{ type: 'text/html' }] },
          attachmentMeta: [{ filename: 'report.pdf', bytes: 2048 }],
          subjectPresent: true,
          fromDisplay: 'n***@news.example.com',
          textLen: 1234,
          htmlPartPresent: true,
          itemTitle: '每周新闻',
          itemDiffSummary: { titleMatches: true, bodyChars: 1234, trackingPixelsBlocked: 2 },
        })
      }
      return baseHandler(url, init)
    })
    await screen.findByText('新闻邮件')
    fireEvent.click(screen.getByRole('button', { name: '解析对照' }))
    fireEvent.change(await screen.findByLabelText('邮件 Message-ID'), { target: { value: 'm1@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: '确定' }))

    const panel = await waitFor(() => qs('data-mail-parse-debug'))
    expect(panel.textContent).toContain('正文长度：1234 字符')
    expect(panel.textContent).toContain('HTML part：有')
    expect(panel.textContent).toContain('跟踪像素拦截：2')
    expect(panel.textContent).toContain('report.pdf')
    expect(document.querySelector('[data-structure-node="multipart/alternative"]')).not.toBeNull()
    expect(document.querySelector('[data-structure-node="text/html"]')).not.toBeNull()
  })

  it('F104: 邮件不存在（404）诚实透出', async () => {
    renderMail((url, init) => {
      if (url.includes('/parse-debug')) {
        return jsonResponse({ error: { type: 'not_found', message: '邮件不存在。' } }, 404)
      }
      return baseHandler(url, init)
    })
    await screen.findByText('新闻邮件')
    fireEvent.click(screen.getByRole('button', { name: '解析对照' }))
    fireEvent.change(await screen.findByLabelText('邮件 Message-ID'), { target: { value: 'gone@x.com' } })
    fireEvent.click(screen.getByRole('button', { name: '确定' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('邮件不存在。')
  })
})

describe('F105 接收规则面板', () => {
  it('F105: 列表/新增（POST）/启停（PATCH）/样本试跑', async () => {
    let rules = [
      { id: 1, listUuid: 'list-1', priority: 0, field: 'from', op: 'contains', value: 'newsletter', action: 'allow', enabled: true },
    ]
    const fetchMock = renderMail((url, init) => {
      const method = init?.method
      if (/\/mail\/lists\/list-1\/rules$/.test(url) && (method === undefined || method === 'GET')) {
        return jsonResponse({ items: rules })
      }
      if (/\/mail\/lists\/list-1\/rules$/.test(url) && method === 'POST') {
        const body = JSON.parse(String(init?.body)) as Record<string, string>
        const rule = { id: 2, listUuid: 'list-1', priority: rules.length, field: body.field, op: body.op, value: body.value, action: body.action, enabled: true }
        rules = [...rules, rule]
        return jsonResponse(rule, 201)
      }
      if (/\/mail\/rules\/1$/.test(url) && method === 'PATCH') {
        rules = rules.map((rule) => (rule.id === 1 ? { ...rule, enabled: false } : rule))
        return jsonResponse(rules[0])
      }
      if (/\/mail\/lists\/list-1\/rules\/dry-run$/.test(url) && method === 'POST') {
        const body = JSON.parse(String(init?.body)) as { value: string }
        if (body.value.includes('deny-me')) {
          return jsonResponse({
            matchedRule: { id: 1, listUuid: 'list-1', priority: 0, field: 'from', op: 'contains', value: 'deny-me', action: 'deny', enabled: true },
            explanation: '第 1 条规则命中：发件人「deny-me」包含「deny-me」→ deny。',
          })
        }
        return jsonResponse({ matchedRule: null, explanation: '没有命中的规则；该样本将被接收（无规则 = 允许）。' })
      }
      return baseHandler(url, init)
    })

    await screen.findByText('新闻邮件')
    fireEvent.click(screen.getByRole('button', { name: '接收规则' }))
    const panel = await waitFor(() => qs('data-mail-rules-panel'))
    await waitFor(() => expect(panel.textContent).toContain('发件人 包含「newsletter」'))

    // 新增
    fireEvent.change(screen.getByLabelText('新规则匹配值'), { target: { value: 'daily-digest' } })
    fireEvent.change(screen.getByLabelText('新规则动作'), { target: { value: 'deny' } })
    fireEvent.click(screen.getByRole('button', { name: /添加/ }))
    await waitFor(() => {
      const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST' && String(init?.body ?? '').includes('daily-digest'))
      expect(post).toBeDefined()
    })
    await waitFor(() => expect(panel.textContent).toContain('daily-digest'))

    // 启停
    fireEvent.click(screen.getByLabelText('启用规则 1'))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith('/mail/rules/1') && init?.method === 'PATCH')).toBe(true)
    })

    // 试跑：命中
    fireEvent.change(screen.getByLabelText('试跑字段'), { target: { value: 'from' } })
    fireEvent.change(screen.getByLabelText('试跑样本值'), { target: { value: 'deny-me@x.com' } })
    fireEvent.click(screen.getByRole('button', { name: '试跑' }))
    await waitFor(() => {
      expect(document.querySelector('[data-dryrun-result]')?.textContent).toContain('拒绝')
    })
  })
})

describe('F106 历史回填向导', () => {
  it('F106: 试运行预览 → 执行 → 结果统计', async () => {
    const fetchMock = renderMail((url, init) => {
      if (url.endsWith('/mail/imap/backfill') && init?.method === 'POST') {
        const body = JSON.parse(String(init?.body)) as { dryRun: boolean; since?: string }
        if (body.dryRun) {
          return jsonResponse({
            dryRun: true,
            sample: [{ uid: 101, subject: '晨报', date: '2026-09-01' }],
            matched: 1,
            uidvalidity: 'u1',
          })
        }
        return jsonResponse({ processed: 1, created: 1, skippedDup: 0, failed: [] })
      }
      return baseHandler(url, init)
    })
    await screen.findByText('新闻邮件')
    fireEvent.click(screen.getByRole('button', { name: '试运行预览' }))
    const result = await waitFor(() => qs('data-backfill-result'))
    expect(result.textContent).toContain('匹配 1 封')
    expect(result.textContent).toContain('晨报')

    fireEvent.click(screen.getByRole('button', { name: '执行回填' }))
    await waitFor(() => {
      expect(result.textContent).toContain('新建 1，重复跳过 0')
    })
    const exec = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST' && String(init?.body).includes('"dryRun":false'))
    expect(exec).toBeDefined()
  })

  it('F106: uidvalidity 变更中止 → 诚实呈现不重试', async () => {
    renderMail((url, init) => {
      if (url.endsWith('/mail/imap/backfill') && init?.method === 'POST') {
        if (JSON.parse(String(init?.body)).dryRun) {
          return jsonResponse({ dryRun: true, sample: [], matched: 3 })
        }
        return jsonResponse({ aborted: true, reason: 'uidvalidity_changed', processed: 0, created: 0, skippedDup: 0, failed: [] })
      }
      return baseHandler(url, init)
    })
    await screen.findByText('新闻邮件')
    fireEvent.click(screen.getByRole('button', { name: '试运行预览' }))
    await waitFor(() => expect(document.querySelector('[data-backfill-result]')).not.toBeNull())
    fireEvent.click(screen.getByRole('button', { name: '执行回填' }))
    const result = await waitFor(() => qs('data-backfill-result'))
    expect(result.textContent).toContain('uidvalidity 已变更')
  })
})

describe('F110 查看会话', () => {
  it('F110: 有序会话链 + 当前标记 + 缺父降级', async () => {
    renderMail((url, init) => {
      if (/\/mail\/lists\/list-1\/messages\/t3%40x.com\/thread/.test(url)) {
        return jsonResponse({
          chain: [
            { id: 't1@x.com', subject: '第一封', date: '2026-09-01T08:00:00Z', current: false },
            { id: 't3@x.com', subject: '本封', date: '2026-09-03T08:00:00Z', current: true },
          ],
          reason: 'parent_missing',
          cycleBroken: false,
        })
      }
      return baseHandler(url, init)
    })
    await screen.findByText('新闻邮件')
    fireEvent.click(screen.getByRole('button', { name: '查看会话' }))
    fireEvent.change(await screen.findByLabelText('邮件 Message-ID'), { target: { value: 't3@x.com' } })
    fireEvent.click(screen.getByRole('button', { name: '确定' }))
    const thread = await waitFor(() => qs('data-mail-thread'))
    const chain = document.querySelector('[data-thread-chain]')
    expect(chain?.textContent).toContain('第一封')
    expect(chain?.textContent).toContain('本封（当前）')
    // 有序：祖先在前，本封在后
    const nodes = Array.from(document.querySelectorAll('[data-thread-node]')).map((n) => n.getAttribute('data-thread-node'))
    expect(nodes).toEqual(['t1@x.com', 't3@x.com'])
    expect(thread.textContent).toContain('会话根缺失')
  })

  it('F110: 本封独立成链（无 reason）不显示降级文案', async () => {
    renderMail((url, init) => {
      if (/\/mail\/lists\/list-1\/messages\/solo%40x.com\/thread/.test(url)) {
        return jsonResponse({
          chain: [{ id: 'solo@x.com', subject: '唯一一封', date: '2026-09-02T08:00:00Z', current: true }],
          reason: null,
          cycleBroken: false,
        })
      }
      return baseHandler(url, init)
    })
    await screen.findByText('新闻邮件')
    fireEvent.click(screen.getByRole('button', { name: '查看会话' }))
    fireEvent.change(await screen.findByLabelText('邮件 Message-ID'), { target: { value: 'solo@x.com' } })
    fireEvent.click(screen.getByRole('button', { name: '确定' }))
    await waitFor(() => expect(document.querySelector('[data-mail-thread]')).not.toBeNull())
    expect(document.querySelector('[data-mail-thread]')?.textContent).not.toContain('会话根缺失')
    expect(document.querySelectorAll('[data-thread-node]').length).toBe(1)
  })
})
