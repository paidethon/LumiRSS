/** WhatsNewTour — N198 版本差异功能导览 Web 测试。
 *
 * 覆盖：清单缺失 → 零渲染；逐项已读（设备本地持久）；关闭导览后
 * 本设备不再弹出（localStorage 持久化，重挂载仍隐藏）；adminOnly
 * 徽标；API 失败（401）静默。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type WhatsNewResponse } from '../api/client'
import WhatsNewTour, { loadWhatsNewLocal } from '../components/WhatsNewTour'

const mocks = vi.hoisted(() => ({
  getWhatsNew: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getWhatsNew: mocks.getWhatsNew,
  }
})

const RESPONSE: WhatsNewResponse = {
  version: '0.2.0',
  sinceVersion: null,
  features: [
    { id: 'N191', title: '用户额度策略包', entry: '/admin', adminOnly: true },
    { id: 'N192', title: '邀请容量仪表', entry: '/admin', adminOnly: true },
    { id: 'N041', title: '今日必读队列', entry: '/' },
  ],
}

function renderTour() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <WhatsNewTour />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  mocks.getWhatsNew.mockResolvedValue(RESPONSE)
})

describe('N198 版本差异功能导览', () => {
  it('有新内容时渲染导览卡并列出条目（含管理员徽标）', async () => {
    renderTour()
    const tour = await screen.findByTestId('whats-new-tour')
    expect(tour).toHaveTextContent('用户额度策略包')
    expect(tour).toHaveTextContent('今日必读队列')
    expect(screen.getAllByText('管理员').length).toBe(2)
    expect(mocks.getWhatsNew).toHaveBeenCalledWith(null, expect.anything())
  })

  it('逐项已读持久化到设备本地（localStorage）', async () => {
    renderTour()
    const firstRead = await screen.findByLabelText('已读：用户额度策略包')
    fireEvent.click(firstRead)
    await waitFor(() => {
      const local = loadWhatsNewLocal()
      expect(local.readIds).toContain('N191')
    })
    // 取消勾选 → 从已读集合移除。
    fireEvent.click(screen.getByLabelText('已读：用户额度策略包'))
    await waitFor(() => {
      expect(loadWhatsNewLocal().readIds).not.toContain('N191')
    })
  })

  it('关闭导览 → dismissedVersion 持久化，重挂载不再弹出', async () => {
    const { unmount } = renderTour()
    fireEvent.click(await screen.findByTestId('whats-new-dismiss'))
    await waitFor(() => expect(loadWhatsNewLocal().dismissedVersion).toBe('0.2.0'))
    unmount()

    renderTour()
    await waitFor(() => expect(screen.queryByTestId('whats-new-tour')).not.toBeInTheDocument())
  })

  it('BFF 无清单（version null）→ 零渲染', async () => {
    mocks.getWhatsNew.mockResolvedValue({ version: null, sinceVersion: null, features: [] })
    renderTour()
    await waitFor(() => expect(screen.queryByTestId('whats-new-tour')).not.toBeInTheDocument())
  })

  it('API 失败（未登录 401 / 网络错误）→ 静默零渲染', async () => {
    mocks.getWhatsNew.mockRejectedValue(new ApiError(401, 'session_required', '登录已过期。'))
    renderTour()
    await waitFor(() => expect(screen.queryByTestId('whats-new-tour')).not.toBeInTheDocument())
  })
})
