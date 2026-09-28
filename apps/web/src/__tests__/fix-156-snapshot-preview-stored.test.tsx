/** FIX-156 — 快照预览与下载同源（stored 版本）；原文快照 vs 实时页面分明。
 *
 * WEB 侧两条内容路径都按 uuid 寻址同一份存储版本，不存在「预览取缓存、
 * 下载取实时重取」的分叉：
 * - 预览：SnapshotsPage「打开原文快照」→ /library/assets/{uuid}/page.html
 *   （BFF 沙箱下发存储版本；title 明示沙箱、不可执行脚本）；
 * - 下载：研究包 ZIP（f088 已核验）把用户勾选的快照 uuid 原样传给
 *   POST /research-pack（includeSnapshots），由服务端打包同一批存储资产。
 *
 * 本文件核验 SnapshotsPage 腿：预览链接 = 存储 asset 路径；实时 URL
 * 只作纯文本展示（不与快照链接混淆）；原文快照/沙箱标签明确。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import SnapshotsPage from '../components/pages/SnapshotsPage'

const SNAPSHOT = {
  uuid: 'snap-12345678-abcd',
  url: 'https://live.example/article',
  bytes: 2048,
  createdAt: '2026-09-20T10:00:00Z',
  deduplicated: false,
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderPage() {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.startsWith('/api/v1/library/snapshots')) {
      return Promise.resolve(
        jsonResponse({ items: [SNAPSHOT], usage: { bytes: 2048, quotaBytes: 1048576 } }),
      )
    }
    return Promise.resolve(jsonResponse({}))
  })
  vi.stubGlobal('fetch', fetchMock)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <SnapshotsPage />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('FIX-156 — 快照预览 = 存储版本；原文快照与实时页面分明', () => {
  it('预览链接按 uuid 寻址存储 asset；实时 URL 仅纯文本；沙箱标签明确', async () => {
    renderPage()

    // 快照行渲染（uuid 短码可见）
    await screen.findByText(SNAPSHOT.uuid.slice(0, 8))

    // 预览链接 = 存储资产路径（uuid 寻址，与下载打包同源），不是实时 URL
    const previewLink = await screen.findByRole('link', { name: '打开原文快照' })
    await waitFor(() =>
      expect(previewLink).toHaveAttribute(
        'href',
        `/api/v1/library/assets/${encodeURIComponent(SNAPSHOT.uuid)}/page.html`,
      ),
    )
    expect(previewLink).toHaveAttribute('target', '_blank')
    expect(previewLink.getAttribute('title')).toContain('沙箱')

    // 实时页面 URL 只作纯文本展示——页面上不存在以实时 URL 为目标的链接
    expect(screen.getByText(SNAPSHOT.url)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: SNAPSHOT.url })).toBeNull()
  })
})
