/** F061 UI — 视图私有订阅对话框：
 * - 启用 → 完整 URL 仅创建时展示一次 + 复制；关闭后显示"已隐藏，可轮换"；
 * - 轮换两步确认（旧地址立即失效提示）→ 新地址展示一次。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ViewFeedTokenDialog } from '../components/ViewFeedTokenDialog'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderDialog(props: {
  view: { id: string; name: string; hasFeedToken: boolean } | null
  open?: boolean
}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <ViewFeedTokenDialog
        open={props.open ?? true}
        onClose={() => {}}
        view={props.view}
      />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F061 私有订阅对话框', () => {
  it('F061: 启用 → 完整 URL 仅展示一次 + 复制；关闭后重开（hasFeedToken）只显示「已隐藏，可轮换」', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        jsonResponse({
          atomPath: '/feeds/views/view-1.abc123def456.atom',
          hasFeedToken: true,
        }),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    const first = renderDialog({ view: { id: 'view-1', name: '我的视图', hasFeedToken: false } })

    // 未启用态：说明 + 启用按钮
    fireEvent.click(screen.getByRole('button', { name: '启用私有订阅' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/search/views/view-1/token/enable',
        expect.objectContaining({ method: 'POST' }),
      )
    })
    // 完整 URL 展示一次（绝对地址）
    const urlInput = await screen.findByLabelText('订阅地址（仅展示一次）')
    expect((urlInput as HTMLInputElement).value).toBe(
      'http://localhost:3000/feeds/views/view-1.abc123def456.atom',
    )
    expect(screen.getByRole('button', { name: /复制地址/ })).toBeInTheDocument()
    expect(screen.getByText(/仅展示这一次/)).toBeInTheDocument()

    // 关闭后重开：视图已是 hasFeedToken → 地址隐藏，可轮换
    first.unmount()
    renderDialog({ view: { id: 'view-1', name: '我的视图', hasFeedToken: true } })
    expect(await screen.findByText(/已隐藏，可轮换/)).toBeInTheDocument()
    expect(screen.queryByLabelText('订阅地址（仅展示一次）')).toBeNull()
  })

  it('F061: 轮换走两步确认（旧地址失效提示）；确认后新地址展示一次', async () => {
    let call = 0
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      call += 1
      const path = (init?.method ?? 'GET') === 'POST' ? String(input) : ''
      const secret = path.includes('/rotate') ? 'newsecret111' : 'oldsecret222'
      return Promise.resolve(
        jsonResponse({ atomPath: `/feeds/views/view-2.${secret}.atom`, hasFeedToken: true }),
      )
    })
    vi.stubGlobal('fetch', fetchMock)
    renderDialog({ view: { id: 'view-2', name: '视图乙', hasFeedToken: true } })

    // 第一步：点击轮换 → 出现确认（旧地址立即失效提示），尚未发请求
    fireEvent.click(await screen.findByRole('button', { name: '轮换地址' }))
    expect(screen.getByText(/旧订阅地址将立即失效/)).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()

    // 取消可退出确认
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(screen.queryByText(/旧订阅地址将立即失效/)).toBeNull()

    // 第二步：确认 → 调用 rotate，新地址展示
    fireEvent.click(screen.getByRole('button', { name: '轮换地址' }))
    fireEvent.click(screen.getByRole('button', { name: '确认轮换' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/search/views/view-2/token/rotate',
        expect.objectContaining({ method: 'POST' }),
      )
    })
    const urlInput = await screen.findByLabelText('订阅地址（仅展示一次）')
    expect((urlInput as HTMLInputElement).value).toContain('newsecret111')
    expect(call).toBeGreaterThanOrEqual(1)
  })
})
