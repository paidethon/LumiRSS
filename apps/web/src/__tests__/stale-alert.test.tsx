/** F001 来源新鲜度预警 —— 阈值设置对话框 + 超期来源面板交互。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { UseMutationResult } from '@tanstack/react-query'
import {
  SourceStaleAlertDialog,
  StaleSourcesPanel,
  staleBasisLabel,
} from '../components/SourceStaleAlert'
import type { StaleSourcesResponse } from '../api/client'

let panelState:
  | { kind: 'data'; body: StaleSourcesResponse }
  | { kind: 'error' }
  | { kind: 'pending' } = { kind: 'data', body: { checked: 0, items: [], generatedAt: '' } }

const mutationSpy = vi.fn()

vi.mock('../api/queries', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/queries')>()
  return {
    ...actual,
    useStaleSourcesQuery: () => ({
      data: panelState.kind === 'data' ? panelState.body : undefined,
      isPending: panelState.kind === 'pending',
      isError: panelState.kind === 'error',
      refetch: vi.fn(),
    }),
    useSetSourceOverrideMutation: () => {
      const result: UseMutationResult<unknown, Error, { feedUrl: string; staleAlertHours?: number | null }> = {
        mutate: mutationSpy,
        isPending: false,
        isError: false,
        reset: vi.fn(),
      } as unknown as UseMutationResult<unknown, Error, { feedUrl: string; staleAlertHours?: number | null }>
      return result
    },
  }
})

function renderWithClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  panelState = { kind: 'data', body: { checked: 0, items: [], generatedAt: '' } }
  mutationSpy.mockClear()
})

describe('F001 StaleSourcesPanel', () => {
  it('F001: 展示超期来源列表并带 basis 标注（latest_entry）', () => {
    panelState = {
      kind: 'data',
      body: {
        checked: 2,
        generatedAt: '',
        items: [
          {
            feedUrl: 'https://slow.example.com/rss',
            subscriptionRef: 's1.a',
            title: '慢速源',
            staleAlertHours: 24,
            lastActivityAt: '2026-09-01T00:00:00Z',
            ageHours: 432.5,
            basis: 'latest_entry',
          },
        ],
      },
    }
    renderWithClient(<StaleSourcesPanel />)
    expect(screen.getByText('慢速源')).toBeTruthy()
    expect(screen.getByText(/约 432.5 小时未更新/)).toBeTruthy()
    expect(screen.getByText(/依据：最新发布时间/)).toBeTruthy()
  })

  it('F001: 空态诚实提示（没有超期来源）', () => {
    renderWithClient(<StaleSourcesPanel />)
    expect(screen.getByText('没有超期来源')).toBeTruthy()
  })

  it('F001: 加载失败显示错误与重试入口', () => {
    panelState = { kind: 'error' }
    renderWithClient(<StaleSourcesPanel />)
    expect(screen.getByRole('alert')).toBeTruthy()
    expect(screen.getByText('重试')).toBeTruthy()
  })
})

describe('F001 SourceStaleAlertDialog', () => {
  it('F001: 输入小时数保存 → 携带 staleAlertHours 的覆盖载荷', async () => {
    renderWithClient(
      <SourceStaleAlertDialog
        open
        onClose={() => {}}
        subscription={{ feedUrl: 'https://f.example/rss', title: '慢速源' }}
      />,
    )
    const input = screen.getByLabelText(/超期阈值/) as HTMLInputElement
    fireEvent.change(input, { target: { value: '48' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(mutationSpy).toHaveBeenCalled())
    expect(mutationSpy).toHaveBeenCalledWith(
      { feedUrl: 'https://f.example/rss', staleAlertHours: 48 },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    )
  })

  it('F001: 非法输入阻止保存（0 / 非整数）', () => {
    renderWithClient(
      <SourceStaleAlertDialog
        open
        onClose={() => {}}
        subscription={{ feedUrl: 'https://f.example/rss', title: '源' }}
      />,
    )
    const input = screen.getByLabelText(/超期阈值/) as HTMLInputElement
    fireEvent.change(input, { target: { value: '0' } })
    expect(screen.getByRole('alert')).toBeTruthy()
    const save = screen.getByRole('button', { name: '保存' }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
  })

  it('F001: 「关闭预警」提交 null（清除维度语义）', async () => {
    renderWithClient(
      <SourceStaleAlertDialog
        open
        onClose={() => {}}
        subscription={{ feedUrl: 'https://f.example/rss', title: '源' }}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: '关闭预警' }))
    await waitFor(() => expect(mutationSpy).toHaveBeenCalled())
    expect(mutationSpy).toHaveBeenCalledWith(
      { feedUrl: 'https://f.example/rss', staleAlertHours: null },
      expect.anything(),
    )
  })
})

describe('F001 staleBasisLabel', () => {
  it('F001: unknown basis 不冒充抓取状态', () => {
    expect(staleBasisLabel('latest_entry')).toContain('发布时间')
    expect(staleBasisLabel('fetch_time')).toContain('抓取时间')
    expect(staleBasisLabel('unknown')).toBe('依据：未知')
  })
})
