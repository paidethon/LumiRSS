/** F114 —— 派生数据保留策略（Web 层）。
 *
 * 默认关（应用为 no-op 且有提示）；启用 + 保存 PUT 载荷（越界天数
 * 收敛为 null = 不启用该类）；预览（只读）→ 保护类如实展示 → 应用
 * （需先预览——武装语义）→ 有界删除结果。fetch 全部 stub。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { StorageRetentionSection } from '../components/settings/StorageRetentionSection'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderSection(handler?: (url: string, init?: RequestInit) => Response) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) =>
    (handler ?? (() => jsonResponse({ enabled: false, aiVersionsDays: null, taskLogDays: null })))(String(input), init),
  )
  vi.stubGlobal('fetch', fetchMock)
  render(
    <QueryClientProvider client={qc}>
      <StorageRetentionSection />
    </QueryClientProvider>,
  )
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F114 派生数据保留策略', () => {
  it('F114: 默认关 → 应用禁用有提示；启用后保存 PUT 载荷（越界天数收敛为 null）', async () => {
    const fetchMock = renderSection((url, init) => {
      if (url.endsWith('/storage/retention') && init?.method === 'PUT') {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>
        return jsonResponse({ enabled: body.enabled === true, aiVersionsDays: body.aiVersionsDays ?? null, taskLogDays: body.taskLogDays ?? null })
      }
      return jsonResponse({ enabled: false, aiVersionsDays: null, taskLogDays: null })
    })
    await screen.findByText('派生数据保留策略')
    // 默认关：应用按钮禁用 + no-op 提示
    expect(screen.getByRole('button', { name: '应用清理' }).hasAttribute('disabled')).toBe(true)
    expect(screen.getByText('策略未启用时「应用」为 no-op。')).toBeTruthy()

    // 越界天数（5 < 30）→ 保存后该类为 null（不启用该类）
    fireEvent.change(screen.getByLabelText('AI 历史版本保留天数'), { target: { value: '5' } })
    fireEvent.change(screen.getByLabelText('任务日志保留天数'), { target: { value: '90' } })
    fireEvent.click(screen.getByRole('button', { name: '保存配置' }))
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')
      expect(put).toBeDefined()
      const body = JSON.parse(String(put?.[1]?.body))
      expect(body.enabled).toBe(false)
      expect(body.aiVersionsDays).toBeNull()
      expect(body.taskLogDays).toBe(90)
    })

    // 启用开关 → PUT enabled=true
    fireEvent.click(screen.getByLabelText('启用保留策略'))
    await waitFor(() => {
      const puts = fetchMock.mock.calls.filter(([, init]) => init?.method === 'PUT')
      const last = JSON.parse(String(puts[puts.length - 1]?.[1]?.body))
      expect(last.enabled).toBe(true)
    })
  })

  it('F114: 预览展示清理计数与保护类 → 应用（武装后）→ 有界删除结果', async () => {
    const fetchMock = renderSection((url, init) => {
      if (url.endsWith('/storage/retention/preview') && init?.method === 'POST') {
        return jsonResponse({
          enabled: true,
          aiVersions: { count: 12, bytes: 48000 },
          taskLog: { count: 34 },
          excluded: { entries: 0, credentials: '保护不清理' },
          quizNote: '测验会话固定保留 24 小时（口径说明，不可配置）。',
        })
      }
      if (url.endsWith('/storage/retention/apply') && init?.method === 'POST') {
        return jsonResponse({ enabled: true, deleted: { aiVersions: 12, taskLog: 30 } })
      }
      return jsonResponse({ enabled: true, aiVersionsDays: 90, taskLogDays: 30 })
    })
    await screen.findByText('派生数据保留策略')

    // 未预览前应用禁用（武装语义）
    expect(screen.getByRole('button', { name: '应用清理' }).hasAttribute('disabled')).toBe(true)

    fireEvent.click(screen.getByRole('button', { name: '预览将清理的内容' }))
    await waitFor(() => {
      const previewResult = document.querySelector('[data-retention-preview-result]')?.textContent ?? ''
      expect(previewResult).toContain('AI 历史版本 12 条')
      expect(previewResult).toContain('任务日志 34 条')
      expect(previewResult).toContain('凭据')
    })

    // 预览后武装解除 → 应用
    fireEvent.click(screen.getByRole('button', { name: '应用清理' }))
    await waitFor(() => {
      expect(document.querySelector('[data-retention-apply-result]')?.textContent).toContain('AI 历史版本 12 条，任务日志 30 条')
    })
    expect(
      fetchMock.mock.calls.some(([url, init]) => String(url).endsWith('/apply') && init?.method === 'POST'),
    ).toBe(true)
  })
})
