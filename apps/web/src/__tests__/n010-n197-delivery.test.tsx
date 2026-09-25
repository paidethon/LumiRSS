/** N010 迁出/迁入向导 + N177 订正标记 + N179 缺刊策略 + N180 日报使用
 * + N189 活动清除 —— 设置/阅读器交付面 Web 测试。fetch 全部 stub。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { GptDigestSection } from '../components/settings/GptDigestSection'
import DigestUsagePanel from '../components/DigestUsagePanel'
import { ActivityPurgeSection } from '../components/settings/ActivityPurgeSection'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

// ===== N177 可见订正标记 + N179 缺刊处理策略（日报设置面） =====

const DIGEST_CONFIG = {
  id: 1,
  name: '默认日报',
  enabled: true,
  hour: 8,
  timezone: 'UTC',
  windowHours: 24,
  limitCount: 12,
  perSourceCap: 2,
  lookbackDays: 7,
  feedUrlAllow: '',
  sourceKind: 'window',
  slots: [],
  days: [],
  weekendHours: [],
  stageModels: {},
  columns: [],
  targetReadingMinutes: 0,
  clusterEnabled: false,
  missedIssuePolicy: 'backfill',
  skipLog: [
    { date: '2026-09-18-08', reason: 'policy_skip' },
    { date: '2026-09-17-08', reason: 'merged_into_next' },
  ],
  lastIssueKey: null,
  lastError: null,
  createdAt: '2026-09-18T00:00:00+00:00',
}

const UNREVISED_ISSUE = {
  issueKey: '2026-09-18',
  status: 'published',
  title: '测试日报',
  sections: [{ heading: '要点', items: [{ summary: '内容。', sourceIds: ['s1'], uncertainty: null }] }],
  refs: { s1: { title: 'T', url: 'https://a.example.com/x', feedTitle: 'F', publishedAt: '', ref: 'e1.abc' } },
  model: 'm',
  meta: {},
  sentenceMap: [],
  note: '',
  revised: false,
  createdAt: '2026-09-18T00:00:00+00:00',
  publishedAt: '2026-09-18T08:00:00+00:00',
  updatedAt: '2026-09-18T08:00:00+00:00',
}

function digestHandler(url: string, init?: RequestInit, issue = UNREVISED_ISSUE): Response {
  if (url.endsWith('/gpt-digest/configs') && (!init || !init.method)) {
    return jsonResponse({ items: [DIGEST_CONFIG] })
  }
  if (url.endsWith('/issues?limit=14') || /\/configs\/\d+\/issues$/.test(url)) {
    return jsonResponse({ items: [issue] })
  }
  if (/\/configs\/\d+\/pool$/.test(url)) return jsonResponse({ items: [], used: [] })
  if (/\/configs\/\d+\/missing-dates/.test(url)) return jsonResponse({ missing: [], existing: [] })
  if (/\/configs\/\d+\/feed/.test(url)) return jsonResponse({ atomPath: '/feeds/gpt-digest/x.atom' })
  return jsonResponse({})
}

function renderDigest(issue = UNREVISED_ISSUE) {
  const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) =>
    digestHandler(String(input), init, issue),
  )
  vi.stubGlobal('fetch', fetchMock)
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <GptDigestSection />
    </QueryClientProvider>,
  )
  return fetchMock
}

describe('N179 缺刊处理策略（设置面）', () => {
  it('策略下拉可选，选择进入保存载荷；skip 记录在 UI 展示', async () => {
    const fetchMock = renderDigest()
    const select = await screen.findByLabelText('缺刊处理策略 默认日报')
    fireEvent.change(select, { target: { value: 'skip' } })
    fireEvent.click(screen.getByRole('button', { name: '保存设置' }))
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        ([url, init]) => String(url).endsWith('/configs/1') && init?.method === 'PUT',
      )
      expect(put).toBeTruthy()
      expect(JSON.parse(String(put?.[1]?.body)).missedIssuePolicy).toBe('skip')
    })
    const log = screen.getByTestId('lumi-digest-skip-log')
    expect(log).toHaveTextContent('2026-09-18-08 · 按策略跳过')
    expect(log).toHaveTextContent('2026-09-17-08 · 已并入下一期')
  })
})

describe('N177 可见订正标记（设置面）', () => {
  it('修订期号 → 订正块（含时间与附注）', async () => {
    renderDigest({
      ...UNREVISED_ISSUE,
      revised: true,
      note: '更正一处数字',
      updatedAt: '2026-09-18T09:30:00+00:00',
    })
    const banner = await screen.findByTestId('lumi-digest-revision-banner')
    expect(banner).toHaveTextContent('已订正')
    expect(banner).toHaveTextContent('2026-09-18T09:30:00+00:00')
    expect(banner).toHaveTextContent('更正一处数字')
  })

  it('未修订期号 → 订正块绝不出现', async () => {
    renderDigest()
    await screen.findByText(/2026-09-18 · 测试日报/)
    expect(screen.queryByTestId('lumi-digest-revision-banner')).toBeNull()
  })
})

// ===== N180 日报材料使用追踪（阅读器面板） =====

describe('N180 日报使用面板', () => {
  it('列出配置/期刊/栏目与跳转锚点；空态诚实', async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/digest-usage')) {
        return jsonResponse({
          items: [
            {
              configId: 1,
              configName: '科技日报',
              issueKey: '2026-09-18',
              issueDate: '2026-09-18',
              section: '纵深',
              sourceId: 's1',
              citationAnchor: '2026-09-18:s1',
              publishedAt: '2026-09-18T08:00:00+00:00',
            },
          ],
        })
      }
      throw new Error(`unexpected fetch: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <DigestUsagePanel entryRef="e1.abc" />
      </QueryClientProvider>,
    )
    const list = await screen.findByTestId('lumi-digest-usage-list')
    expect(list).toHaveTextContent('科技日报 · 2026-09-18')
    expect(list).toHaveTextContent('纵深')
    const jump = screen.getByTestId('lumi-digest-usage-jump')
    expect(jump).toHaveAttribute('title', '引用位置 2026-09-18:s1')
  })

  it('无引用 → 诚实空态', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ items: [] })),
    )
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <DigestUsagePanel entryRef="e1.abc" />
      </QueryClientProvider>,
    )
    expect(await screen.findByTestId('lumi-digest-usage-empty')).toBeInTheDocument()
    expect(screen.queryByTestId('lumi-digest-usage-list')).toBeNull()
  })
})

// ===== N189 清除活动记录 =====

describe('N189 清除活动记录（隐私）', () => {
  it('预览显示各桶计数，确认后展示删除数与保留说明', async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = (init?.method ?? 'GET').toUpperCase()
      if (url.includes('/me/activity-purge/preview')) {
        return jsonResponse({
          before: '2026-06-01T00:00:00+00:00',
          counts: { loginEvents: 2, aiTaskLogs: 1, searchSnapshots: 0 },
          retained: ['已读/收藏/笔记等业务状态不受影响（它们不是活动记录）'],
        })
      }
      if (url.endsWith('/me/activity-purge') && method === 'POST') {
        return jsonResponse({
          before: '2026-06-01T00:00:00+00:00',
          deleted: { loginEvents: 2, aiTaskLogs: 1, searchSnapshots: 0 },
          retained: ['已读/收藏/笔记等业务状态不受影响（它们不是活动记录）'],
        })
      }
      throw new Error(`unexpected fetch: ${url} ${method}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ActivityPurgeSection />
      </QueryClientProvider>,
    )
    fireEvent.change(screen.getByLabelText('清除此日期之前'), { target: { value: '2026-06-01' } })
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    const preview = await screen.findByTestId('lumi-activity-purge-preview')
    expect(preview).toHaveTextContent('登录事件')
    expect(preview).toHaveTextContent('2 条')
    fireEvent.click(screen.getByTestId('lumi-activity-purge-confirm'))
    const result = await screen.findByTestId('lumi-activity-purge-result')
    expect(result).toHaveTextContent('删除 2 条')
    expect(result).toHaveTextContent('业务状态不受影响')
  })
})
