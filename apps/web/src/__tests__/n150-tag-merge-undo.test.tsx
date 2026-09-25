/** N150 标签合并撤销 — TagMergeDialog 撤销接线（黑盒 fetch stub）。
 *
 * - 合并成功 → 对话框进入「已合并」态并展示 撤销本次合并 按钮；
 * - 点击撤销 → POST /api/v1/tags/merge/undo；成功 → 显示恢复结果；
 * - 409（源名已被占用，含重复撤销）/ 404（超 24h 窗口）→ 错误诚实内联。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { QueryClientProvider as QCP } from '@tanstack/react-query'
import { TagMergeDialog } from '../components/TagMergeDialog'
import type { TagSummary } from '../api/client'

void QCP

const TAGS: TagSummary[] = [
  { id: 1, name: '源标签', count: 2 },
  { id: 2, name: '目标标签', count: 1 },
]

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function setup(undoResponse: () => Response) {
  const requests: { url: string; method: string; body: unknown }[] = []
  const mock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const request = {
      url,
      method: (init?.method ?? 'GET').toUpperCase(),
      body: typeof init?.body === 'string' ? JSON.parse(init.body) : null,
    }
    requests.push(request)
    if (url.startsWith('/api/v1/tags/merge/undo')) {
      return Promise.resolve(undoResponse())
    }
    if (url === '/api/v1/tags/merge') {
      return Promise.resolve(
        jsonResponse({ targetId: 2, movedBindings: 1, dedupedBindings: 1 }),
      )
    }
    if (url.startsWith('/api/v1/tags/merge/preview')) {
      return Promise.resolve(
        jsonResponse({ sourceId: 1, targetId: 2, bindings: 2, overlaps: 1, willMove: 1 }),
      )
    }
    return Promise.resolve(jsonResponse({}))
  })
  vi.stubGlobal('fetch', mock)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <TagMergeDialog tagList={TAGS} onClose={() => {}} />
    </QueryClientProvider>,
  )
  return requests
}

async function mergeAndReachUndoState() {
  fireEvent.change(screen.getByLabelText('源标签'), { target: { value: '1' } })
  fireEvent.change(screen.getByLabelText('目标标签'), { target: { value: '2' } })
  // 预览（merge/preview）就绪后确认按钮才从 disabled 变为可点——
  // disabled 期间的 click 是 no-op，必须等待可交互再点。
  const confirm = await screen.findByRole('button', { name: '确认合并' })
  await waitFor(() => expect(confirm).toBeEnabled())
  fireEvent.click(confirm)
  expect(await screen.findByText(/24 小时内可以撤销/)).toBeInTheDocument()
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('N150 标签合并撤销（TagMergeDialog）', () => {
  it('合并成功 → 撤销按钮；点击撤销 → POST undo 并显示恢复结果', async () => {
    const requests = setup(() =>
      jsonResponse({
        sourceTagId: 10,
        name: '源标签',
        targetTagId: 2,
        restoredBindings: 2,
      }),
    )
    await mergeAndReachUndoState()

    fireEvent.click(screen.getByTestId('merge-undo'))
    expect(await screen.findByText(/已撤销：源标签「源标签」已恢复/)).toBeInTheDocument()
    expect(screen.getByText(/2 个绑定/)).toBeInTheDocument()
    await waitFor(() => {
      const post = requests.find((r) => r.url === '/api/v1/tags/merge/undo')
      expect(post?.method).toBe('POST')
    })
  })

  it('重复撤销（源标签已重建，409）→ 错误诚实内联，不静默', async () => {
    setup(() =>
      jsonResponse(
        { error: { type: 'tag_merge_source_recreated', message: '源标签已存在，无法重复撤销。' } },
        409,
      ),
    )
    await mergeAndReachUndoState()

    fireEvent.click(screen.getByTestId('merge-undo'))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /源标签已存在，无法重复撤销/,
    )
    // 撤销失败后按钮仍在（可再次尝试或关闭），不进入成功态。
    expect(screen.getByTestId('merge-undo')).toBeInTheDocument()
  })

  it('超过 24h 窗口（404）→ 错误诚实内联', async () => {
    setup(() =>
      jsonResponse(
        { error: { type: 'tag_merge_undo_not_found', message: '合并撤销窗口（24 小时）已过期。' } },
        404,
      ),
    )
    await mergeAndReachUndoState()

    fireEvent.click(screen.getByTestId('merge-undo'))
    expect(await screen.findByRole('alert')).toHaveTextContent(/24 小时/)
  })
})
