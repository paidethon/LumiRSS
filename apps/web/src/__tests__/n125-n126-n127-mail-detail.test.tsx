/** N125/N126/N127 UI — 邮件详情：附件下载 chips + 已跳过清单、文本/HTML
 * 切换（零远程请求）、被阻止的外链媒体、中性身份提示与诚实文案。
 * 统一 stub 全局 fetch（与 f104 同一约定，真实 client 解析路径）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MailDetailDialog } from '../components/MailDetailDialog'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const LIST_UUID = 'list-n125'

const MESSAGES = {
  items: [
    {
      messageId: 'm1@example.com',
      subject: '第 42 期',
      sender: 'Newsletter <news@example.com>',
      receivedAt: '2026-09-22T08:00:00Z',
      attachmentCount: 2,
      skippedAttachments: 1,
      blockedMediaCount: 1,
      hasIdentityHints: true,
    },
  ],
}

let detailPayload: Record<string, unknown>

const DETAIL = {
  messageId: 'm1@example.com',
  listUuid: LIST_UUID,
  subject: '第 42 期',
  sender: 'Newsletter <news@example.com>',
  receivedAt: '2026-09-22T08:00:00Z',
  text: '纯文本版本的正文。',
  html: '<p>HTML 版本的正文</p>',
  blockedMedia: ['https://tracker.example/pixel.gif'],
  attachments: [
    { id: 'att-1', filename: 'report.pdf', mime: 'application/pdf', size: 2048 },
  ],
  skippedAttachments: [
    {
      filename: 'evil.exe',
      bytes: 512,
      mime: 'application/octet-stream',
      status: 'skipped_unsafe',
      reason: '附件类型不在允许名单（脚本/可执行等），未保存。',
    },
  ],
  identityHints: {
    fromAddress: 'news@example.com',
    replyToMismatch: true,
    replyToAddress: 'different@example.net',
  },
}

function renderDialog() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MailDetailDialog listUuid={LIST_UUID} onClose={() => {}} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  detailPayload = DETAIL
  const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (method === 'GET' && url.endsWith('/messages')) {
      return Promise.resolve(jsonResponse(MESSAGES))
    }
    if (method === 'GET' && url.endsWith('/detail')) {
      return Promise.resolve(jsonResponse(detailPayload))
    }
    return Promise.resolve(jsonResponse({}))
  })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('N125/126/127 邮件详情', () => {
  it('消息清单 → 详情：附件 chip 带 下载（指向 /mail/attachments/{id}）；已跳过如实列出', async () => {
    renderDialog()
    fireEvent.click(await screen.findByRole('button', { name: /第 42 期/ }))

    expect(await screen.findByText(/2\.0 KB/)).toBeInTheDocument()

    const download = screen.getByRole('link', { name: /report\.pdf/ })
    expect(download.getAttribute('href')).toBe('/api/v1/mail/attachments/att-1')
    expect(download.getAttribute('download')).toBe('report.pdf')

    const skipped = screen.getByText(/已跳过：evil\.exe/)
    expect(skipped).toBeInTheDocument()
    expect(skipped.closest('ul')).toHaveAttribute('data-mail-attachments-skipped')
    expect(screen.getByText(/附件类型不在允许名单/)).toBeInTheDocument()
  })

  it('N126：文本/HTML 切换纯本地——切换不发起任何网络请求', async () => {
    // 包装现有 stub（保留实现），只统计调用。
    const underlying = window.fetch
    const fetchSpy = vi.fn((...args: Parameters<typeof fetch>) =>
      underlying(...args),
    )
    vi.stubGlobal('fetch', fetchSpy)
    renderDialog()
    fireEvent.click(await screen.findByRole('button', { name: /第 42 期/ }))

    await waitFor(() => {
      expect(document.querySelector('[data-mail-body-text]')).not.toBeNull()
    })
    expect(document.querySelector('[data-mail-body-text]')).toHaveTextContent(
      '纯文本版本的正文。',
    )

    const callsBefore = fetchSpy.mock.calls.length
    fireEvent.click(screen.getByRole('button', { name: 'HTML' }))
    expect(document.querySelector('[data-mail-body-html]')).toHaveTextContent(
      'HTML 版本的正文',
    )
    fireEvent.click(screen.getByRole('button', { name: '文本' }))
    expect(document.querySelector('[data-mail-body-text]')).toHaveTextContent(
      '纯文本版本的正文。',
    )
    // 切换期间零新增请求（更不允许指向远程站点的请求）
    expect(fetchSpy.mock.calls.length).toBe(callsBefore)
    vi.unstubAllGlobals()

    // 详情本身只请求了一次（切换不重新拉取）
    const detailCalls = fetchSpy.mock.calls.filter((c) =>
      String(c[0]).endsWith('/detail'),
    )
    expect(detailCalls.length).toBe(1)
  })

  it('N126：被阻止的外链媒体清单如实展示', async () => {
    renderDialog()
    fireEvent.click(await screen.findByRole('button', { name: /第 42 期/ }))
    expect(await screen.findByText(/被阻止的外链媒体（1）/)).toBeInTheDocument()
    expect(screen.getByText('https://tracker.example/pixel.gif')).toBeInTheDocument()
  })

  it('N127：中性身份提示 + 无 SPF/DKIM 验证声明的诚实文案', async () => {
    renderDialog()
    fireEvent.click(await screen.findByRole('button', { name: /第 42 期/ }))
    const hints = await screen.findByText('提示：发件人与回复地址不一致')
    expect(hints.closest('[data-mail-identity-hints]')).not.toBeNull()
    expect(
      screen.getByText('允许客户端不验证 SPF/DKIM，无法确认真实性。'),
    ).toBeInTheDocument()
  })

  it('N127：无提示时不渲染身份提示区', async () => {
    detailPayload = { ...DETAIL, identityHints: null }
    renderDialog()
    fireEvent.click(await screen.findByRole('button', { name: /第 42 期/ }))
    await screen.findByText('纯文本版本的正文。')
    expect(document.querySelector('[data-mail-identity-hints]')).toBeNull()
  })
})
