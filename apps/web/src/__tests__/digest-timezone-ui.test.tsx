/** F008 摘要时区 + 下次发送时间 —— DigestBlock UI。 */

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

function digestFixture(over: Partial<DigestSettings> = {}): DigestSettings {
  return {
    enabled: true,
    hour: 9,
    source: 'read_later',
    limitCount: 10,
    smtpHost: 'smtp.example.com',
    smtpPort: 465,
    smtpUser: 'digest@example.com',
    fromAddr: 'digest@example.com',
    toAddr: 'me@example.com',
    timezone: 'Asia/Shanghai',
    nextSendAt: '2026-09-20T09:00:00+08:00',
    lastSentAt: null,
    lastError: null,
    passwordConfigured: true,
    ...over,
  } as DigestSettings
}

function imapFixture(): MailImapSettings {
  return {
    configured: false,
    host: '',
    port: 993,
    user: '',
    folder: 'INBOX',
    ssl: true,
    listUuid: '',
    intervalSeconds: 300,
    enabled: true,
    passwordConfigured: false,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.listMailBridgeLists.mockResolvedValue({ items: [] })
  mocks.getMailImapSettings.mockResolvedValue(imapFixture())
  mocks.getDigestSettings.mockResolvedValue(digestFixture())
  mocks.updateDigestSettings.mockResolvedValue(digestFixture())
})

describe('F008 摘要时区 + 下次发送', () => {
  it('F008: 时区输入渲染并随保存提交；下次发送时间展示', async () => {
    render(withProviders(<MailSection />))
    const tz = (await screen.findByLabelText('发送时区（IANA，留空 = 服务器本地）')) as HTMLInputElement
    expect(tz.value).toBe('Asia/Shanghai')
    expect(screen.getByText(/下次发送：/)).toBeInTheDocument()
    fireEvent.change(tz, { target: { value: 'Europe/Berlin' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() =>
      expect(mocks.updateDigestSettings).toHaveBeenCalledWith(
        expect.objectContaining({ timezone: 'Europe/Berlin' }),
      ),
    )
  })

  it('F008: 非法时区 → 后端 422 错误信息原样显示', async () => {
    mocks.updateDigestSettings.mockRejectedValue(
      new ApiError(422, 'invalid_timezone', '不是合法的 IANA 时区名称：Mars/Base'),
    )
    render(withProviders(<MailSection />))
    fireEvent.change(await screen.findByLabelText('发送时区（IANA，留空 = 服务器本地）'), {
      target: { value: 'Mars/Base' },
    })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    expect(await screen.findByText(/不是合法的 IANA 时区名称：Mars\/Base/)).toBeInTheDocument()
  })
})
