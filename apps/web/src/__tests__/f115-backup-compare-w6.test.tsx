/** F115 —— 备份比较（Web 层）。
 *
 * 备份历史行勾选两份成功的完整备份 → 「比较所选」→ POST
 * /backups/compare → 差异逐类渲染（A/B/差值 + schema 版本）；
 * incomparable 诚实展示（绝不显示为 0）；identical 明示一致；
 * 未选满两份时按钮禁用 + 提示。fetch 全部 stub。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { BackupHistoryCard } from '../components/settings/backup/BackupHistoryCard'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const JOBS = [
  {
    id: 'job-a',
    type: 'full',
    status: 'succeeded',
    createdAt: '2026-09-18T08:00:00Z',
    summary: { filename: 'lumi-a.zip', sizeBytes: 1024, components: ['lumi'], target: 'local' },
  },
  {
    id: 'job-b',
    type: 'full',
    status: 'succeeded',
    createdAt: '2026-09-19T08:00:00Z',
    summary: { filename: 'lumi-b.zip', sizeBytes: 2048, components: ['lumi'], target: 'local' },
  },
]

function renderCard(handler?: (url: string, init?: RequestInit) => Response) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) =>
    (handler ?? (() => jsonResponse(JOBS)))(String(input), init),
  )
  vi.stubGlobal('fetch', fetchMock)
  render(
    <QueryClientProvider client={qc}>
      <BackupHistoryCard />
    </QueryClientProvider>,
  )
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F115 备份比较', () => {
  it('F115: 勾选两份 → 比较 → 差异分类渲染 + incomparable 诚实', async () => {
    const fetchMock = renderCard((url, init) => {
      if (url.endsWith('/backups/compare') && init?.method === 'POST') {
        const body = JSON.parse(String(init?.body)) as { aId: string; bId: string }
        expect(body.aId).toBe('job-a')
        expect(body.bId).toBe('job-b')
        return jsonResponse({
          identical: false,
          categories: [
            { name: 'lumi.sqlite', aCount: 120, bCount: 135, delta: -15 },
            { name: 'freshrss-data', aCount: 10, bCount: 10, delta: 0 },
          ],
          schemaVersions: { a: 64, b: 65 },
          incomparable: ['未知/旧格式段名：legacy_count'],
        })
      }
      return jsonResponse(JOBS)
    })
    await screen.findByText('备份历史')
    fireEvent.click(await screen.findByLabelText('选择比较 job-a'))
    // 只选一份时禁用 + 提示
    expect(screen.getByRole('button', { name: /比较所选/ }).hasAttribute('disabled')).toBe(true)
    expect(screen.getByText('勾选两份成功的完整备份以比较。')).toBeTruthy()
    fireEvent.click(await screen.findByLabelText('选择比较 job-b'))
    fireEvent.click(screen.getByRole('button', { name: /比较所选/ }))

    await waitFor(() => {
      expect(document.querySelector('[data-backup-compare-result]')?.textContent ?? '').toContain('两份备份存在差异')
    })
    expect(document.querySelector('[data-compare-category="lumi.sqlite"]')?.textContent).toContain('差 -15')
    expect(document.querySelector('[data-backup-compare-result]')?.textContent).toContain('schema：A 64 → B 65')
    expect(document.querySelector('[data-compare-incomparable]')?.textContent).toContain('legacy_count')
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
    expect(String(post?.[0])).toContain('/backups/compare')
  })

  it('F115: 完全一致 → 明示一致；关闭比较可清除', async () => {
    renderCard((url, init) => {
      if (url.endsWith('/backups/compare') && init?.method === 'POST') {
        return jsonResponse({ identical: true, categories: [], schemaVersions: { a: 65, b: 65 }, incomparable: [] })
      }
      return jsonResponse(JOBS)
    })
    await screen.findByText('备份历史')
    fireEvent.click(await screen.findByLabelText('选择比较 job-a'))
    fireEvent.click(await screen.findByLabelText('选择比较 job-b'))
    fireEvent.click(screen.getByRole('button', { name: /比较所选/ }))
    await waitFor(() => {
      expect(document.querySelector('[data-backup-compare-result]')?.textContent ?? '').toContain('两份备份内容一致')
    })
    fireEvent.click(screen.getByRole('button', { name: '关闭比较' }))
    expect(document.querySelector('[data-backup-compare-result]')).toBeNull()
  })
})
