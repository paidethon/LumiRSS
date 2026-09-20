/** F062 UI — 译文修订面板：保存/撤销修订（PUT/DELETE）、重新生成的
 * 保留/覆盖两种选择、源文变化失配标记、危险 HTML 按纯文本转义。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import TranslationRevisionPanel from '../components/TranslationRevisionPanel'
import type { TranslationSegmentState } from '../api/types'
import type { ArticleBlock } from '../lib/translation-blocks'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const SEGMENTS: TranslationSegmentState[] = [
  { index: 0, status: 'success', translatedText: '机器译文零。', cached: true, revisionStale: false },
  {
    index: 1,
    status: 'success',
    translatedText: '机器译文壹。',
    cached: true,
    userRevision: '我的修订壹<script>alert(1)</script>',
    revisedAt: '2026-09-01T00:00:00Z',
    revisionStale: true,
  },
]

const BLOCKS: ArticleBlock[] = [
  { index: 0, text: 'Source zero.' },
  { index: 1, text: 'Source one EDITED.' },
]

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <TranslationRevisionPanel entryRef="e1.f062" segments={SEGMENTS} blocks={BLOCKS} />
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

describe('F062 译文修订面板', () => {
  it('F062: 编辑译文保存 → PUT 修订；修订按纯文本渲染（危险 HTML 被转义）；失配标记显示', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(
          jsonResponse({ index: 0, userRevision: '我的新译', revisedAt: '2026-09-19T00:00:00Z', revisionStale: false }),
        ),
      )
    vi.stubGlobal('fetch', fetchMock)
    const { container } = renderPanel()

    // 打开面板，选中默认第 1 段（index 0）
    fireEvent.click(screen.getByRole('button', { name: /译文修订/ }))
    // 失配标记：index 1 的段 revisionStale → 摘要处显示（选中前不显示）
    expect(screen.queryByText(/原文已更新/)).toBeNull()

    // 编辑并保存
    const textarea = screen.getByLabelText('第 1 段译文修订')
    fireEvent.change(textarea, { target: { value: '我的新译' } })
    fireEvent.click(screen.getByRole('button', { name: '保存修订' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/entries/e1.f062/translation/segments/0/revision',
        expect.objectContaining({ method: 'PUT' }),
      )
    })

    // 修订文本按纯文本渲染：切换到含危险修订的段 → 文本节点原样展示，
    // 不存在任何被解析出的 <script> 元素
    fireEvent.change(screen.getByLabelText('选择要修订的段落'), {
      target: { value: '1' },
    })
    await waitFor(() => {
      expect(screen.getByLabelText('第 2 段译文修订')).toBeInTheDocument()
    })
    expect(screen.getByText(/原文已更新/)).toBeInTheDocument()
    expect(container.querySelector('script')).toBeNull()
    expect(container.textContent).toContain('<script>alert(1)</script>')
  })

  it('F062: 重新生成默认保留修订（body 无覆盖标志）；全部覆盖需确认且带 overwriteRevisions:true', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(() => Promise.resolve(jsonResponse({ segments: [] })))
    vi.stubGlobal('fetch', fetchMock)
    renderPanel()

    fireEvent.click(screen.getByRole('button', { name: /译文修订/ }))

    // 默认重生成：body 不含 overwriteRevisions
    fireEvent.click(screen.getByRole('button', { name: '重新生成（保留我的修订）' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/entries/e1.f062/translation/segments/generate',
        expect.objectContaining({ method: 'POST' }),
      )
    })
    const defaultBody = JSON.parse((fetchMock.mock.calls[0]?.[1] as RequestInit).body as string)
    expect(defaultBody.overwriteRevisions).toBeUndefined()

    // 全部覆盖：确认对话框 → 确认后 body 带 overwriteRevisions:true
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    fireEvent.click(screen.getByRole('button', { name: '全部覆盖' }))
    await waitFor(() => {
      expect(confirmSpy).toHaveBeenCalled()
    })
    await waitFor(() => {
      expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(2)
    })
    const overwriteBody = JSON.parse(
      (fetchMock.mock.calls[fetchMock.mock.calls.length - 1]?.[1] as RequestInit).body as string,
    )
    expect(overwriteBody.overwriteRevisions).toBe(true)
  })

  it('F062: 撤销修订 → DELETE；机器原文可见（查看机器译文）', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((_input: RequestInfo | URL, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'DELETE') {
          return Promise.resolve(new Response(null, { status: 204 }))
        }
        return Promise.resolve(jsonResponse({ segments: [] }))
      })
    vi.stubGlobal('fetch', fetchMock)
    renderPanel()

    fireEvent.click(screen.getByRole('button', { name: /译文修订/ }))
    fireEvent.change(screen.getByLabelText('选择要修订的段落'), {
      target: { value: '1' },
    })
    // 机器原文诚实展示（纯文本）
    await waitFor(() => {
      expect(screen.getByText(/机器原文：/)).toBeInTheDocument()
    })
    expect(screen.getByText(/机器译文壹。/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '撤销修订' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/entries/e1.f062/translation/segments/1/revision',
        expect.objectContaining({ method: 'DELETE' }),
      )
    })
  })
})
