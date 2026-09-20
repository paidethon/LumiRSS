/** F087 UI — 检查链接对话框：状态分类渲染、仅复查失败、URL 不改写
 * （redirect 只报告 finalUrl）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CheckLinksDialog } from '../components/CheckLinksDialog'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const REFS = ['library:11111111-1111-4111-8111-111111111111', 'library:22222222-2222-4222-8222-222222222222']

function renderDialog() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <CheckLinksDialog refs={REFS} onClose={() => {}} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F087 书签失效检查', () => {
  it('F087: 状态分类渲染（ok/redirect/timeout/ssrf）；redirect 只报告不改写', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        jsonResponse({
          items: [
            { ref: REFS[0], status: 'redirect', httpStatus: 301, finalUrl: 'https://new.example/a', checkedAt: '2026-09-19T00:00:00Z' },
            { ref: REFS[1], status: 'timeout', checkedAt: '2026-09-19T00:00:00Z' },
          ],
        }),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    fireEvent.click(screen.getByRole('button', { name: '开始检查' }))
    expect(await screen.findByText('重定向 · HTTP 301')).toBeInTheDocument()
    expect(screen.getByText('超时')).toBeInTheDocument()
    // 负向契约：检查不改写 URL（对话框只读展示，无任何保存按钮）。
    expect(screen.queryByRole('button', { name: /保存|应用/ })).not.toBeInTheDocument()
  })

  it('F087: 仅复查失败只发送失败 ref 并合并结果', async () => {
    let checkRounds = 0
    const fetchMock = vi.fn().mockImplementation((_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body ?? '{}')) as { refs: string[] }
      checkRounds += 1
      return Promise.resolve(
        jsonResponse({
          items: body.refs.map((ref) => {
            if (ref === REFS[1]) {
              // 第一轮超时；复查轮恢复 ok。
              return checkRounds === 1
                ? { ref, status: 'timeout', checkedAt: '2026-09-19T00:00:00Z' }
                : { ref, status: 'ok', httpStatus: 200, checkedAt: '2026-09-19T00:01:00Z' }
            }
            return { ref, status: 'redirect', httpStatus: 301, finalUrl: 'https://n.example', checkedAt: '2026-09-19T00:00:00Z' }
          }),
        }),
      )
    })
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    fireEvent.click(screen.getByRole('button', { name: '开始检查' }))
    await screen.findByText('超时')
    fireEvent.click(screen.getByRole('button', { name: '仅复查失败（1）' }))
    await waitFor(() => {
      expect(screen.getByText('正常 · HTTP 200')).toBeInTheDocument()
    })
    // 合并：原来的 redirect 结果仍在。
    expect(screen.getByText('重定向 · HTTP 301')).toBeInTheDocument()
    const lastCall = fetchMock.mock.calls.at(-1)!
    const body = JSON.parse(String(lastCall[1]?.body ?? '{}')) as { refs: string[] }
    expect(body.refs).toEqual([REFS[1]])
  })
})
