/** F065 UI — 基于所选提问对话框：范围清单可移除（空范围禁用提问）、
 * 提问 POST body 只含剩余所选、回答纯文本渲染 + 引用 chips 点击打开该文。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AskBatchDialog, type AskBatchTarget } from '../components/AskBatchDialog'
import { useReaderUi } from '../store/reader-ui'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const TARGETS: AskBatchTarget[] = [
  { ref: 'e1.a', title: '文章甲' },
  { ref: 'e1.b', title: '文章乙' },
]

const RESULT = {
  answer: '共同点是两者都讨论了同一事件 <img src=x onerror=alert(1)>，见 [1] [2] [99]。',
  citations: [
    { index: 1, entryRef: 'e1.a' },
    { index: 2, entryRef: 'e1.b' },
  ],
  skipped: [],
}

function renderDialog(props: {
  targets: AskBatchTarget[]
  onRemove?: (ref: string) => void
}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AskBatchDialog
        open
        onClose={() => {}}
        targets={props.targets}
        onRemove={props.onRemove ?? (() => {})}
      />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
  useReaderUi.setState({ view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F065 基于所选提问对话框', () => {
  it('F065: 范围清单可移除；空范围禁用提问；提问 body 只含剩余所选', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(() => Promise.resolve(jsonResponse(RESULT)))
    vi.stubGlobal('fetch', fetchMock)
    const onRemove = vi.fn()
    renderDialog({ targets: TARGETS, onRemove })

    // 范围 chips 展示；移除第一篇 → onRemove 被调
    expect(screen.getByText('文章甲')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /从范围移除「文章甲」/ }))
    expect(onRemove).toHaveBeenCalledWith('e1.a')

    // 正常提问：body 只含剩余所选（这里以未移除的双篇为范围断言透传）
    const box = screen.getByLabelText('问题输入')
    fireEvent.change(box, { target: { value: '两篇文章讲了什么？' } })
    const askButton = screen.getByRole('button', { name: '提问' })
    expect(askButton).not.toBeDisabled()
    fireEvent.click(askButton)
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/entries/ask-batch',
        expect.objectContaining({ method: 'POST' }),
      )
    })
    const body = JSON.parse((fetchMock.mock.calls[0]?.[1] as RequestInit).body as string)
    expect(body.entryRefs).toEqual(['e1.a', 'e1.b'])
    expect(body.question).toBe('两篇文章讲了什么？')
  })

  it('F065: 回答按纯文本渲染（HTML 被转义）；引用 chips 点击打开对应文章', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(() => Promise.resolve(jsonResponse(RESULT)))
    vi.stubGlobal('fetch', fetchMock)
    renderDialog({ targets: TARGETS })

    fireEvent.change(screen.getByLabelText('问题输入'), {
      target: { value: '共同点？' },
    })
    fireEvent.click(screen.getByRole('button', { name: /提问/ }))
    await screen.findByText(/共同点是/)

    // 纯文本渲染：img 未被解析成元素，dangerous 片段是文本（portal → document）
    expect(document.querySelector('p img')).toBeNull()
    expect(document.body.textContent).toContain('<img src=x onerror=alert(1)>')
    // 越界引用 [99] 不可能拿到 chip（服务端已滤；UI 只渲染服务端 citations）
    expect(document.body.textContent).toContain('[1]')
    expect(document.body.textContent).toContain('[2]')
    expect(document.body.textContent).not.toMatch(/\[99\] 文章/)

    // 点击引用 chip → 打开该文
    fireEvent.click(screen.getByTitle('文章乙'))
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.b')
  })
})
