/** N188 —— 数据保留到期提醒（Web 层）。
 *
 * dueSoon → 横幅展示 dueAt/影响计数/保护类；「推迟」调用 postpone
 * 端点后横幅切换为已推迟状态；推迟不触发 apply（负向断言）。
 * fetch 全部 stub。
 */

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

function setup(notice: unknown) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url.endsWith('/storage/retention') && method === 'GET') {
      return jsonResponse({ enabled: true, aiVersionsDays: 30, taskLogDays: null })
    }
    if (url.endsWith('/storage/retention/notice') && method === 'GET') {
      return jsonResponse(notice)
    }
    if (url.endsWith('/storage/retention/postpone') && method === 'POST') {
      return jsonResponse({ postponedUntil: '2026-10-24T00:00:00+00:00', days: 7 })
    }
    if (url.endsWith('/storage/retention/preview') && method === 'POST') {
      return jsonResponse({
        enabled: true,
        aiVersions: { count: 3, bytes: 1200 },
        taskLog: { count: 0 },
        excluded: {},
        quizNote: '测验会话固定保留 24 小时（口径说明，不可配置）。',
      })
    }
    if (url.endsWith('/storage/retention/apply') && method === 'POST') {
      return jsonResponse({ enabled: true, deleted: { aiVersions: 0, taskLog: 0 } })
    }
    return jsonResponse({}, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  render(
    <QueryClientProvider client={qc}>
      <StorageRetentionSection />
    </QueryClientProvider>,
  )
  return fetchMock
}

const DUE_SOON: Record<string, unknown> = {
  enabled: true,
  dueSoon: true,
  dueAt: '2026-09-27T00:00:00+00:00',
  noticeWindowDays: 7,
  postponedUntil: null,
  affectedCounts: { aiVersions: { count: 0, bytes: 0 }, taskLog: { count: 0 } },
  protected: ['entries', 'annotations', 'notes', 'cards', 'credentials', 'runningJobs'],
  quizNote: '',
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('N188 到期提醒', () => {
  it('dueSoon 横幅：dueAt + 保护类说明 + 推迟按钮', async () => {
    const fetchMock = setup(DUE_SOON)
    await screen.findByText('派生数据保留策略')
    await waitFor(() => {
      expect(document.querySelector('[data-retention-notice]')).not.toBeNull()
    })
    const banner = document.querySelector('[data-retention-notice]')?.textContent ?? ''
    expect(banner).toContain('保留策略即将到期')
    expect(banner).toContain('2026-09-27')
    expect(banner).toContain('人工笔记')
    expect(banner).toContain('手动点击')
    expect(document.querySelector('[data-retention-postpone="7"]')).not.toBeNull()
    // 未发生任何 apply 调用
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/apply'))).toBe(false)
  })

  it('点击「推迟 7 天」→ 调用 postpone 端点；随后横幅转为已推迟状态', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    let currentNotice = DUE_SOON
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url.endsWith('/storage/retention') && method === 'GET') {
        return jsonResponse({ enabled: true, aiVersionsDays: 30, taskLogDays: null })
      }
      if (url.endsWith('/storage/retention/notice') && method === 'GET') {
        return jsonResponse(currentNotice)
      }
      if (url.endsWith('/storage/retention/postpone') && method === 'POST') {
        currentNotice = {
          ...DUE_SOON,
          dueSoon: false,
          postponedUntil: '2026-10-01T00:00:00+00:00',
        }
        return jsonResponse({ postponedUntil: '2026-10-01T00:00:00+00:00', days: 7 })
      }
      return jsonResponse({}, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(
      <QueryClientProvider client={qc}>
        <StorageRetentionSection />
      </QueryClientProvider>,
    )
    await screen.findByText('派生数据保留策略')
    await waitFor(() => {
      expect(document.querySelector('[data-retention-due-soon]')?.getAttribute('data-retention-due-soon')).toBe('true')
    })
    fireEvent.click(screen.getByRole('button', { name: '推迟 7 天' }))
    await waitFor(() => {
      const postponed = document.querySelector('[data-retention-postponed]')
      expect(postponed?.textContent).toContain('已推迟至 2026-10-01')
    })
    const post = fetchMock.mock.calls.find(
      ([url, init]) => String(url).endsWith('/postpone') && init?.method === 'POST',
    )
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ days: 7 })
  })

  it('未启用策略 → 无横幅', async () => {
    setup({ enabled: false, dueSoon: false, dueAt: null, noticeWindowDays: 7, postponedUntil: null, affectedCounts: {}, protected: [], quizNote: '' })
    await screen.findByText('派生数据保留策略')
    await waitFor(() => {
      // 配置区正常渲染
      expect(screen.getByText('派生数据保留策略')).toBeTruthy()
    })
    expect(document.querySelector('[data-retention-notice]')).toBeNull()
  })
})
