/** R19 邮件简报页（NewsletterPage）Web 测试。
 *
 * - 默认 tab「已发送」：列表项 = 主题/时间/状态/来源/收件人数；
 * - tab 切换（失败/草稿）：按状态查询 + 空态文案（草稿/计划诚实空）；
 * - 详情抽屉：正文快照渲染（DOMPurify 边界后）；
 * - 历史不可用态：bodyAvailable=false → 「历史记录不可用」，不伪造正文；
 * - 失败行重试：调用 retry API（服务端只补投未送达收件人）；
 * - 「管理连接/发送设置」深链设置 mail 分类（settings-bridge 事件）。
 *
 * 统一 vi.mock('../api/newsletter')，断言 BFF 契约调用；jsdom 无
 * matchMedia → 抽屉走移动 ActionSheet 形态（内容断言不受影响）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type {
  NewsletterIssueDetail,
  NewsletterIssueSummary,
} from '../api/newsletter'
import NewsletterPage from '../components/pages/NewsletterPage'

const mocks = vi.hoisted(() => ({
  listNewsletterIssues: vi.fn(),
  getNewsletterIssue: vi.fn(),
  retryNewsletterIssue: vi.fn(),
}))

vi.mock('../api/newsletter', () => ({
  listNewsletterIssues: mocks.listNewsletterIssues,
  getNewsletterIssue: mocks.getNewsletterIssue,
  retryNewsletterIssue: mocks.retryNewsletterIssue,
}))

function renderWithProviders(ui: ReactNode): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

function issue(over: Partial<NewsletterIssueSummary> = {}): NewsletterIssueSummary {
  return {
    id: 1,
    subject: 'LumiRSS 文章摘要',
    status: 'sent',
    source: 'mail',
    origin: 'manual',
    itemCount: 3,
    recipientCount: 1,
    error: null,
    createdAt: '2026-10-01T08:00:00+00:00',
    sentAt: '2026-10-01T08:00:05+00:00',
    ...over,
  }
}

function sentDetail(over: Partial<NewsletterIssueDetail> = {}): NewsletterIssueDetail {
  return {
    ...issue(),
    bodyAvailable: true,
    text: '1. 每周精选',
    html: '<h2>LumiRSS 文章摘要</h2><ol><li>每周精选</li></ol>',
    dedupeKey: '',
    providerReceipt: '',
    recipients: [{ address: 'r***@local', status: 'sent', error: null, sentAt: '2026-10-01T08:00:05+00:00' }],
    ...over,
  }
}

function failedDetail(): NewsletterIssueDetail {
  return {
    ...issue({ id: 2, status: 'failed', sentAt: null, error: '发送失败（1/1 个收件人）：send_failed' }),
    bodyAvailable: false,
    text: null,
    html: null,
    dedupeKey: '',
    providerReceipt: '',
    recipients: [
      { address: 'r***@local', status: 'failed', error: 'SMTP 发送失败。', sentAt: null },
    ],
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.listNewsletterIssues.mockResolvedValue({ items: [issue()] })
  mocks.getNewsletterIssue.mockResolvedValue(sentDetail())
  mocks.retryNewsletterIssue.mockResolvedValue({
    issueId: 2,
    status: 'sent',
    sentCount: 1,
    skippedCount: 0,
  })
})

async function openDetail(id: number): Promise<void> {
  fireEvent.click(
    await screen.findByRole('button', { name: /LumiRSS 文章摘要/ }),
  )
  // 抽屉打开的标志：详情元数据区渲染（两种详情形态都有）。
  await screen.findByText('发送方式')
  expect(mocks.getNewsletterIssue).toHaveBeenCalledWith(
    id,
    expect.anything(),
  )
}

describe('NewsletterPage', () => {
  it('默认「已发送」tab：列表项展示主题/时间/状态/来源/收件人数', async () => {
    renderWithProviders(<NewsletterPage />)
    expect(mocks.listNewsletterIssues).toHaveBeenCalledWith('sent', expect.anything())
    const row = await screen.findByRole('button', { name: /LumiRSS 文章摘要/ })
    expect(row).toHaveTextContent('已发送')
    expect(row).toHaveTextContent('来源 mail')
    expect(row).toHaveTextContent('手动 · 1 个收件人')
  })

  it('切换「失败」tab：按状态查询并显示错误摘要', async () => {
    mocks.listNewsletterIssues.mockResolvedValue({
      items: [
        issue({
          id: 2,
          status: 'failed',
          sentAt: null,
          error: '发送失败（1/1 个收件人）：send_failed',
        }),
      ],
    })
    renderWithProviders(<NewsletterPage />)
    fireEvent.click(screen.getByRole('tab', { name: '失败' }))
    const row = await screen.findByRole('button', { name: /LumiRSS 文章摘要/ })
    expect(mocks.listNewsletterIssues).toHaveBeenCalledWith('failed', expect.anything())
    expect(row).toHaveTextContent('失败')
    expect(row).toHaveTextContent('发送失败（1/1 个收件人）')
  })

  it('「草稿」tab：诚实空态 + 深链设置 mail 分类', async () => {
    mocks.listNewsletterIssues.mockResolvedValue({ items: [] })
    const opened: Array<string | undefined> = []
    const onOpenSettings = (event: Event): void => {
      const detail = (event as CustomEvent<{ category?: string }>).detail
      opened.push(detail?.category)
    }
    window.addEventListener('lumi:open-settings', onOpenSettings)
    try {
      renderWithProviders(<NewsletterPage />)
      fireEvent.click(screen.getByRole('tab', { name: '草稿' }))
      expect(
        await screen.findByText('外发简报没有草稿'),
      ).toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: '打开发送设置' }))
      await waitFor(() => expect(opened).toEqual(['mail']))
    } finally {
      window.removeEventListener('lumi:open-settings', onOpenSettings)
    }
  })

  it('详情抽屉：正文快照经净化边界渲染', async () => {
    renderWithProviders(<NewsletterPage />)
    await openDetail(1)
    const body = screen.getByTestId('newsletter-body')
    expect(body).toHaveTextContent('每周精选')
    // 快照的 html 形态优先；文本形态也在 DTO 中（不强制同时渲染）。
    expect(mocks.getNewsletterIssue).toHaveBeenCalledTimes(1)
  })

  it('历史不可用态：无快照显示「历史记录不可用」，不伪造正文', async () => {
    mocks.listNewsletterIssues.mockResolvedValue({
      items: [failedDetail()],
    })
    mocks.getNewsletterIssue.mockResolvedValue(failedDetail())
    renderWithProviders(<NewsletterPage />)
    await openDetail(2)
    expect(await screen.findByText('历史记录不可用')).toBeInTheDocument()
    expect(screen.queryByTestId('newsletter-body')).not.toBeInTheDocument()
    // 错误在列表行与详情各出现一次；收件账目标注未送达。
    expect(screen.getAllByText('发送失败（1/1 个收件人）：send_failed').length).toBeGreaterThan(0)
    expect(
      screen.getAllByText(/r\*\*\*@local（未送达）/).length,
    ).toBeGreaterThan(0)
  })

  it('失败行重试：调用 retry API（服务端只补投未送达收件人）', async () => {
    mocks.listNewsletterIssues.mockResolvedValue({
      items: [failedDetail()],
    })
    mocks.getNewsletterIssue.mockResolvedValue(failedDetail())
    renderWithProviders(<NewsletterPage />)
    await openDetail(2)
    fireEvent.click(screen.getByRole('button', { name: '重试未送达的收件人' }))
    await waitFor(() =>
      expect(mocks.retryNewsletterIssue).toHaveBeenCalledWith(2),
    )
    await waitFor(() =>
      expect(screen.getByText(/已补发 1 个收件人，跳过 0 个已送达/)).toBeInTheDocument(),
    )
  })

  it('列表加载失败：错误空态 + 重试', async () => {
    mocks.listNewsletterIssues.mockRejectedValue(new Error('BFF 不可达'))
    renderWithProviders(<NewsletterPage />)
    expect(await screen.findByText('发送记录加载失败')).toBeInTheDocument()
    expect(screen.getByText('BFF 不可达')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    await waitFor(() => expect(mocks.listNewsletterIssues).toHaveBeenCalledTimes(2))
  })
})
