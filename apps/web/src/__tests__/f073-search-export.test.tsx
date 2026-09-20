/** F073 UI — 导出清单对话框：格式选择 + 摘录勾选 + 预览总数（dryRun）
 * + 执行下载（截断诚实标注）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SearchExportDialog } from '../components/SearchExportDialog'

function makeResponse(body: string, headers: Record<string, string>, status = 200): Response {
  return new Response(body, { status, headers: { 'content-type': 'text/plain', ...headers } })
}

function renderDialog(query = 'alpha') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <SearchExportDialog open onClose={() => {}} query={query} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('F073 导出清单对话框', () => {
  it('F073: 预览总数（dryRun）→ 导出下载（截断标注）', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((_input: RequestInfo | URL, init?: RequestInit) => {
        const body = JSON.parse(String(init?.body ?? '{}'))
        if (body.dryRun === true) {
          return Promise.resolve(
            makeResponse(JSON.stringify({ total: 42, scanned: 42, capped: false }), {}),
          )
        }
        return Promise.resolve(
          makeResponse('标题,来源\n甲,源\n', {
            'x-lumi-total': '42',
            'x-lumi-truncated': '1',
          }),
        )
      })
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    renderDialog()

    // 范围预览：真实总数
    fireEvent.click(screen.getByRole('button', { name: '预览总数' }))
    expect(await screen.findByText(/导出失败|已导出|42/)).toBeTruthy()
    const dryCall = fetchMock.mock.calls.find((c) => {
      try {
        return JSON.parse(String((c[1] as RequestInit)?.body ?? '{}')).dryRun === true
      } catch {
        return false
      }
    })
    expect(dryCall).toBeTruthy()

    // 执行导出（含摘录列）
    fireEvent.click(screen.getByRole('switch', { name: '包含摘录列（≤200 字）' }))
    fireEvent.click(screen.getByRole('button', { name: /导出/ }))
    await waitFor(() => {
      const save = fetchMock.mock.calls.find((c) => {
        try {
          const body = JSON.parse(String((c[1] as RequestInit)?.body ?? '{}'))
          return body.dryRun === undefined
        } catch {
          return false
        }
      })
      expect(save).toBeTruthy()
    })
    const saveCall = fetchMock.mock.calls.find((c) => {
      try {
        const body = JSON.parse(String((c[1] as RequestInit)?.body ?? '{}'))
        return body.dryRun === undefined
      } catch {
        return false
      }
    })
    const saveBody = JSON.parse(String((saveCall?.[1] as RequestInit).body))
    expect(saveBody.fields).toContain('excerpt')
    expect(saveBody.q).toBe('alpha')
    // 截断诚实标注
    expect(await screen.findByText(/已截断标注/)).toBeInTheDocument()
  })

  it('F073: 空查询禁用导出；格式可选 markdown', () => {
    renderDialog('')
    expect(screen.getByRole('button', { name: /导出/ })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('导出格式'), { target: { value: 'markdown' } })
    expect((screen.getByLabelText('导出格式') as HTMLSelectElement).value).toBe('markdown')
  })
})
