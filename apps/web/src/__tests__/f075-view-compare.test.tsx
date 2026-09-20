/** F075 UI — 视图对照对话框：选第二视图 → 三区（共同/仅A/仅B）计数 +
 * 前 20 条 chips 打开 + complete:false 警示。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ViewCompareDialog } from '../components/ViewCompareDialog'
import type { SavedSearchView } from '../api/types'
import { useReaderUi } from '../store/reader-ui'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const BASE = { id: 'v-a', name: '视图甲' } as SavedSearchView
const OTHER = { id: 'v-b', name: '视图乙' } as SavedSearchView

const RESULT = {
  common: ['ref.common1'],
  onlyA: ['ref.onlya1'],
  onlyB: ['ref.onlyb1'],
  counts: { a: 3, b: 2, common: 1, onlyA: 2, onlyB: 1 },
  complete: false,
}

function renderDialog() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <ViewCompareDialog open onClose={() => {}} baseView={BASE} otherViews={[BASE, OTHER]} />
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

describe('F075 视图对照对话框', () => {
  it('F075: 选第二视图 → 三区计数 + chips 打开 + complete:false 警示', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(() => Promise.resolve(jsonResponse(RESULT)))
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    fireEvent.click(screen.getByRole('button', { name: '视图乙' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/search/views/compare',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ aId: 'v-a', bId: 'v-b' }),
        }),
      )
    })
    // 三区 + 计数
    expect(await screen.findByText(/共同（1）/)).toBeInTheDocument()
    expect(screen.getByText(/仅 A（1）/)).toBeInTheDocument()
    expect(screen.getByText(/仅 B（1）/)).toBeInTheDocument()
    expect(screen.getByText(/共同 1 · 仅 A 2 · 仅 B 1/)).toBeInTheDocument()
    // complete:false 警示
    expect(screen.getByText(/结果不完整/)).toBeInTheDocument()
    // chips 点击打开
    fireEvent.click(screen.getByTitle('ref.common1'))
    expect(useReaderUi.getState().selectedEntryRef).toBe('ref.common1')
  })

  it('F075: complete → 不显示不完整警示；零命中区显示「无」', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() =>
        Promise.resolve(
          jsonResponse({
            common: [],
            onlyA: [],
            onlyB: ['ref.x'],
            counts: { a: 0, b: 1, common: 0, onlyA: 0, onlyB: 1 },
            complete: true,
          }),
        ),
      ),
    )
    renderDialog()
    fireEvent.click(screen.getByRole('button', { name: '视图乙' }))
    expect(await screen.findByText(/共同 0 · 仅 A 0 · 仅 B 1/)).toBeInTheDocument()
    expect(screen.queryByText(/结果不完整/)).toBeNull()
    // 共同区为空 → 「无」
    const sections = screen.getAllByText('无')
    expect(sections.length).toBeGreaterThanOrEqual(2)
  })
})
