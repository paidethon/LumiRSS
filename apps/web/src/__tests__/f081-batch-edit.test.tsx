/** F081 UI — 批量编辑对话框：字段勾选+预览零写入+应用+仅失败重试；
 * 未勾选字段不出现在 patch（原值保持）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BatchEditDialog } from '../components/BatchEditDialog'

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
      <BatchEditDialog refs={REFS} onClose={() => {}} />
    </QueryClientProvider>,
  )
}

function postBody(fetchMock: ReturnType<typeof vi.fn>, urlSuffix: string): unknown {
  const call = fetchMock.mock.calls.find(
    (c) => String(c[0]).endsWith(urlSuffix) && (c[1]?.method ?? 'GET') === 'POST',
  )
  return JSON.parse(String(call?.[1]?.body ?? '{}')) as unknown
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F081 批量元数据编辑', () => {
  it('F081: 勾选字段进 patch、未勾选字段保持 undefined；预览→应用成功', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/batch-edit/preview')) {
        return Promise.resolve(
          jsonResponse({
            items: REFS.map((ref) => ({
              ref,
              before: { title: 'T', tags: ['a'], workspaceIds: [] },
              after: { title: 'T【藏】', tags: ['a', 'b'], workspaceIds: [] },
            })),
          }),
        )
      }
      if (url.endsWith('/batch-edit')) {
        return Promise.resolve(jsonResponse({ items: REFS.map((ref) => ({ ref, ok: true })), applied: 2, failed: 0 }))
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    // 只勾选标题后缀与添加标签；工作区 / 移除标签不勾选。
    fireEvent.click(screen.getByLabelText('勾选：标题追加后缀'))
    fireEvent.change(screen.getByLabelText('标题后缀'), { target: { value: '【藏】' } })
    fireEvent.click(screen.getByLabelText('勾选：添加标签'))
    fireEvent.change(screen.getByLabelText('要添加的标签'), { target: { value: 'b' } })

    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    await screen.findByText('变更前')
    const previewBody = postBody(fetchMock, '/batch-edit/preview') as { patch: Record<string, unknown>; refs: string[] }
    expect(previewBody.patch.titleSuffix).toBe('【藏】')
    expect(previewBody.patch.tagsAdd).toEqual(['b'])
    expect('tagsRemove' in previewBody.patch).toBe(false)
    expect('workspaceId' in previewBody.patch).toBe(false)
    expect(previewBody.refs).toEqual(REFS)

    fireEvent.click(screen.getByRole('button', { name: '应用到 2 条' }))
    await screen.findByText(/成功 2 条/)
    const applyBody = postBody(fetchMock, '/batch-edit') as { patch: Record<string, unknown> }
    expect(applyBody.patch.titleSuffix).toBe('【藏】')
  })

  it('F081: 部分失败→结果列出原因→仅失败重试（只带失败 ref）', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/batch-edit/preview')) {
        return Promise.resolve(
          jsonResponse({
            items: REFS.map((ref) => ({
              ref,
              before: { title: 'T', tags: [], workspaceIds: [] },
              after: { title: 'T', tags: [], workspaceIds: ['ws'] },
            })),
          }),
        )
      }
      if (url.endsWith('/batch-edit')) {
        return Promise.resolve(
          jsonResponse({
            items: [
              { ref: REFS[0], ok: true },
              { ref: REFS[1], ok: false, error: 'workspace_missing' },
            ],
            applied: 1,
            failed: 1,
          }),
        )
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    fireEvent.click(screen.getByLabelText('勾选：移动到工作区'))
    fireEvent.change(screen.getByLabelText('目标工作区 ID'), { target: { value: 'ws' } })
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    await screen.findByText('变更前')
    fireEvent.click(screen.getByRole('button', { name: '应用到 2 条' }))
    await screen.findByText(/失败 1 条/)
    expect(screen.getByText(/workspace_missing/)).toBeInTheDocument()

    fetchMock.mockClear()
    fireEvent.click(screen.getByRole('button', { name: '仅重试失败（1）' }))
    await waitFor(() => {
      const retry = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/batch-edit'))
      const body = JSON.parse(String(retry?.[1]?.body ?? '{}')) as { refs: string[] }
      expect(body.refs).toEqual([REFS[1]])
    })
  })
})
