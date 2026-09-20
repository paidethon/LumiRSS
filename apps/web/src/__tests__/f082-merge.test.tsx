/** F082 UI — 合并对话框：选两条→字段对照+策略→确认；同条校验、
 * 409 merged_already 诚实报错。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MergeDialog, type MergeCandidate } from '../components/MergeDialog'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const ITEMS: MergeCandidate[] = [
  { ref: 'library:11111111-1111-4111-8111-111111111111', title: '主：阅读器指南' },
  { ref: 'library:22222222-2222-4222-8222-222222222222', title: '副：阅读器指南（重复）' },
]

function renderDialog() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MergeDialog items={ITEMS} onClose={() => {}} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F082 重复资料合并', () => {
  it('F082: 字段对照渲染 + 批注追加策略 + 确认合并', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/merge/preview')) {
        return Promise.resolve(
          jsonResponse({
            primaryRef: ITEMS[0]!.ref,
            duplicateRef: ITEMS[1]!.ref,
            fields: [
              { field: 'title', primary: '主：阅读器指南', duplicate: '副：阅读器指南（重复）' },
              { field: 'note', primary: '主备注', duplicate: '副备注' },
            ],
            annotationCount: 3,
            assetUuids: ['snap-1'],
          }),
        )
      }
      if (url.endsWith('/merge')) {
        return Promise.resolve(
          jsonResponse({
            mergedRef: ITEMS[0]!.ref,
            removedRef: ITEMS[1]!.ref,
            tagsUnion: ['a', 'b'],
            movedAnnotations: 3,
            trashed: true,
          }),
        )
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    fireEvent.change(screen.getByLabelText('选择主记录'), { target: { value: ITEMS[0]!.ref } })
    fireEvent.change(screen.getByLabelText('选择副记录'), { target: { value: ITEMS[1]!.ref } })
    fireEvent.click(screen.getByRole('button', { name: '预览对照' }))

    // 对照表在 merge-preview 容器内渲染双方字段值。
    const previewBox = await screen.findByTestId('merge-preview')
    expect(previewBox).toHaveTextContent('主：阅读器指南')
    expect(previewBox).toHaveTextContent('副：阅读器指南（重复）')
    expect(screen.getByText(/批注 3 条/)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('批注策略'), { target: { value: 'append' } })
    fireEvent.click(screen.getByRole('button', { name: '确认合并' }))

    await screen.findByText(/副记录已放入回收站/)
    const mergeCall = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/merge'))
    const body = JSON.parse(String(mergeCall?.[1]?.body ?? '{}')) as {
      primaryRef: string
      duplicateRef: string
      policy: { title: string; note: string }
    }
    expect(body.primaryRef).toBe(ITEMS[0]!.ref)
    expect(body.duplicateRef).toBe(ITEMS[1]!.ref)
    expect(body.policy).toEqual({ title: 'primary', note: 'append' })
  })

  it('F082: 已合并对再请求 409 merged_already → 诚实报错', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/merge/preview')) {
        return Promise.resolve(
          jsonResponse({
            primaryRef: ITEMS[0]!.ref,
            duplicateRef: ITEMS[1]!.ref,
            fields: [],
            annotationCount: 0,
            assetUuids: [],
          }),
        )
      }
      if (url.endsWith('/merge')) {
        return Promise.resolve(
          jsonResponse({ error: { type: 'merged_already', message: '该重复对已合并过。' } }, 409),
        )
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    fireEvent.change(screen.getByLabelText('选择主记录'), { target: { value: ITEMS[0]!.ref } })
    fireEvent.change(screen.getByLabelText('选择副记录'), { target: { value: ITEMS[1]!.ref } })
    fireEvent.click(screen.getByRole('button', { name: '预览对照' }))
    await screen.findByText(/确认合并/)
    fireEvent.click(screen.getByRole('button', { name: '确认合并' }))
    await waitFor(() => {
      expect(screen.getByText(/merged_already|已合并过/)).toBeInTheDocument()
    })
  })
})
