/** F007 IMAP 启停 —— ImapForm 首批组件测试（此前为零）。
 *
 * 覆盖：字段渲染（含 enabled 开关）、开关切换后保存载荷携带 enabled、
 * 测试连接失败路径（错误文案诚实透出）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type { DigestSettings, MailImapSettings } from '../api/client'
import { ApiError } from '../api/client'
import { MailSection } from '../components/settings/MailSection'

const mocks = vi.hoisted(() => ({
  listMailBridgeLists: vi.fn(),
  getMailImapSettings: vi.fn(),
  updateMailImapSettings: vi.fn(),
  testMailImap: vi.fn(),
  pollMailImap: vi.fn(),
  getDigestSettings: vi.fn(),
  sendDigestNow: vi.fn(),
  updateDigestSettings: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    listMailBridgeLists: mocks.listMailBridgeLists,
    getMailImapSettings: mocks.getMailImapSettings,
    updateMailImapSettings: mocks.updateMailImapSettings,
    testMailImap: mocks.testMailImap,
    pollMailImap: mocks.pollMailImap,
    getDigestSettings: mocks.getDigestSettings,
    sendDigestNow: mocks.sendDigestNow,
    updateDigestSettings: mocks.updateDigestSettings,
  }
})

function withProviders(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

function imapFixture(over: Partial<MailImapSettings> = {}): MailImapSettings {
  return {
    configured: true,
    host: 'imap.example.com',
    port: 993,
    user: 'reader@example.com',
    folder: 'INBOX',
    ssl: true,
    listUuid: '',
    intervalSeconds: 300,
    enabled: true,
    passwordConfigured: true,
    ...over,
  }
}

function digestFixture(): DigestSettings {
  return {
    enabled: false,
    hour: 8,
    source: 'read_later',
    limitCount: 10,
    smtpHost: 'smtp.example.com',
    smtpPort: 465,
    smtpUser: 'digest@example.com',
    smtpPasswordConfigured: true,
    from: 'digest@example.com',
    to: [],
    timezone: '',
    lastSentAt: null,
    lastError: null,
  } as unknown as DigestSettings
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.listMailBridgeLists.mockResolvedValue({ items: [] })
  mocks.getMailImapSettings.mockResolvedValue(imapFixture())
  mocks.getDigestSettings.mockResolvedValue(digestFixture())
})

describe('F007 IMAP 启停', () => {
  it('F007: 渲染字段与启停开关（默认开），关闭后保存载荷携带 enabled=false', async () => {
    mocks.updateMailImapSettings.mockResolvedValue(imapFixture({ enabled: false }))
    render(withProviders(<MailSection />))

    expect((await screen.findByLabelText('服务器（host）')) as HTMLInputElement).toBeDefined()
    const toggle = screen.getByRole('checkbox', { name: '启用 IMAP 抓取' }) as HTMLInputElement
    expect(toggle.checked).toBe(true)
    // 状态徽标显示已配置
    expect(screen.getByText(/已配置 · 每 300s 轮询/)).toBeInTheDocument()

    fireEvent.click(toggle)
    expect(toggle.checked).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: '保存 IMAP 设置' }))

    await waitFor(() =>
      expect(mocks.updateMailImapSettings).toHaveBeenCalledWith(
        expect.objectContaining({ enabled: false, host: 'imap.example.com' }),
      ),
    )
  })

  it('F007: 测试连接失败 → 错误文案诚实透出，不伪造成功', async () => {
    mocks.testMailImap.mockRejectedValue(
      new ApiError(502, 'imap_connect_failed', 'IMAP 连接失败：服务器不可达'),
    )
    render(withProviders(<MailSection />))
    fireEvent.click(await screen.findByRole('button', { name: /测试连接/ }))
    expect(await screen.findByText(/连接测试失败：IMAP 连接失败：服务器不可达/)).toBeInTheDocument()
  })
})
