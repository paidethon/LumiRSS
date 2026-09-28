/** FIX-155 — 剪藏批量导入（BulkPasteDialog）健壮性核验。
 *
 * 既有 n121 测试已覆盖：payload（空行剔除/urls/target）、逐条
 * created|duplicate|failed + reason（部分失败不影响整批）、来源 URL
 * 逐行展示（来源标识随结果保留）。本文件补足缺口：
 * - 提交进行中（pending）按钮禁用 + 二次点击不再发请求（重复提交守卫）；
 * - 来源标识：target=clip 时结果行保留每个 URL（创建来源不丢失）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { BulkPasteDialog } from '../components/BulkPasteDialog'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

/** 手动 resolve 的 deferred，控制 pending 窗口。 */
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('FIX-155 — 剪藏批量导入', () => {
  it('pending 期间按钮禁用，二次点击不重复提交；完成后结果保留来源 URL', async () => {
    const gate = deferred<Response>()
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/library/bulk-links')) return gate.promise
      return Promise.resolve(jsonResponse({ items: [], nextCursor: null }))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderWithClient(<BulkPasteDialog target="clip" onClose={() => {}} />)

    const textarea = screen.getByLabelText('批量链接（每行一个）')
    fireEvent.change(textarea, { target: { value: 'https://clip.example/one\n' } })

    const bulkCalls = () =>
      fetchMock.mock.calls.filter((c) => String(c[0]).endsWith('/library/bulk-links'))

    const submit = document.querySelector('[data-bulk-paste-submit]') as HTMLButtonElement
    expect(submit).not.toBeNull()
    expect(submit).not.toBeDisabled()

    // 第一次点击 → 进入 pending：按钮禁用 + 处理中文案
    fireEvent.click(submit)
    await waitFor(() => expect(bulkCalls()).toHaveLength(1))
    await waitFor(() => expect(submit).toBeDisabled())
    expect(screen.getByText('处理中…')).toBeInTheDocument()

    // pending 中再点两次 → 不产生新请求（重复提交守卫）
    fireEvent.click(submit)
    fireEvent.click(submit)
    await Promise.resolve()
    expect(bulkCalls()).toHaveLength(1)

    // 完成 → 逐条结果 + 来源 URL 保留
    gate.resolve(jsonResponse({
      target: 'clip',
      created: 1,
      duplicate: 0,
      failed: 0,
      items: [{ url: 'https://clip.example/one', status: 'created' }],
    }))
    const results = await screen.findByRole('status')
    expect(results).toHaveTextContent('新建 1')
    expect(within(results).getByText('https://clip.example/one').closest('li')).toHaveAttribute(
      'data-bulk-result',
      'created',
    )
    // 全程只发过一次请求
    expect(bulkCalls()).toHaveLength(1)
  })
})
