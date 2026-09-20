/** F067 UI — 对照分析页：模式切换 + 分节渲染（claim/evidence 带来源
 * 编号 chip）+「未验证」标注 + 页头警示 + 失败重试保留旧结果。 */

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
  commonPoints: ['都讨论了开放标准'],
  differences: [
    {
      topic: '路线之争',
      positions: [
        { entry: 1, claim: '甲支持开放标准优先' },
        { entry: 2, claim: '乙支持商业生态优先' },
      ],
    },
  ],
  evidence: [
    { entry: 1, quote: '开放标准是核心', verified: true },
    { entry: 2, quote: '这句话原文不存在', verified: false },
  ],
  uncertainties: ['样本时间窗较短'],
  materials: [
    { index: 1, entryRef: 'e1.a', title: '文章甲' },
    { index: 2, entryRef: 'e1.b', title: '文章乙' },
  ],
  skipped: [],
}

function renderDialog() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AskBatchDialog open onClose={() => {}} targets={TARGETS} onRemove={() => {}} />
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

describe('F067 对照分析页', () => {
  it('F067: 切到对照分析 → POST compare；分节渲染 + 来源 chip + 未验证标注 + 页头警示', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((input: RequestInfo | URL) => {
        if (String(input).endsWith('/compare')) {
          return Promise.resolve(jsonResponse(RESULT))
        }
        return Promise.resolve(jsonResponse({}))
      })
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    fireEvent.click(screen.getByRole('tab', { name: '对照分析' }))
    // 页头警示（模型生成，可能不准确）
    expect(screen.getByText(/对照分析为模型生成，可能不准确/)).toBeInTheDocument()
    // 问题输入隐藏（对照页不需要）
    expect(screen.queryByLabelText('问题输入')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '开始对照分析' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/entries/compare',
        expect.objectContaining({ method: 'POST' }),
      )
    })
    const body = JSON.parse((fetchMock.mock.calls[0]?.[1] as RequestInit).body as string)
    expect(body.entryRefs).toEqual(['e1.a', 'e1.b'])

    // 分节渲染
    expect(await screen.findByText('共同点')).toBeInTheDocument()
    expect(screen.getByText('分歧')).toBeInTheDocument()
    expect(screen.getByText('证据')).toBeInTheDocument()
    expect(screen.getByText('不确定')).toBeInTheDocument()
    expect(screen.getByText('甲支持开放标准优先')).toBeInTheDocument()
    // quote 核验诚实标注
    expect(screen.getByText('已核验')).toBeInTheDocument()
    expect(screen.getByText('未验证')).toBeInTheDocument()
    // 来源编号 chip 可点击打开对应文章
    fireEvent.click(screen.getAllByRole('button', { name: '[2]' })[0])
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.b')
  })

  it('F067: 失败 → 显示错误 + 重试按钮；旧结果保留在组件态', async () => {
    let fail = true
    const fetchMock = vi
      .fn()
      .mockImplementation((input: RequestInfo | URL) => {
        if (String(input).endsWith('/compare')) {
          if (fail) {
            return Promise.resolve(
              jsonResponse(
                { error: { type: 'comparison_invalid', message: '模型输出不符合结构' } },
                502,
              ),
            )
          }
          return Promise.resolve(jsonResponse(RESULT))
        }
        return Promise.resolve(jsonResponse({}))
      })
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    fireEvent.click(screen.getByRole('tab', { name: '对照分析' }))
    fireEvent.click(screen.getByRole('button', { name: '开始对照分析' }))
    expect(await screen.findByRole('alert')).toBeInTheDocument()

    // 首次失败：无结果，但有重试按钮
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()

    // 重试成功 → 结果渲染
    fail = false
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByText('共同点')).toBeInTheDocument()
    expect(screen.getByText('都讨论了开放标准')).toBeInTheDocument()
  })
})
