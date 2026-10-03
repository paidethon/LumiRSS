/** R13：AI 日报生成流程与配置两层结构测试（历史名 GPT 日报；路由标识
 * gpt-digest 为兼容保留，不得出现在新文案/aria）。
 *
 * 断言：配置面两层（基础默认可见、高级折叠）；手动生成的服务端真实
 * 阶段进度（run-status）+ 可取消 + 取消/失败后可重试；预览（无副作
 * 用）→ 生成草稿 → 审阅并发布两步（发布响应即时反映状态）；用户可
 * 见文本与 aria 标签不含 "GPT" 字样。fetch 全部 stub，绝不触网。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { GptDigestSection } from '../components/settings/GptDigestSection'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const CONFIG = {
  id: 1,
  name: '默认日报',
  enabled: true,
  hour: 8,
  timezone: 'Asia/Shanghai',
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
  lastIssueKey: '2026-09-18',
  lastError: null,
  createdAt: '2026-09-18T00:00:00+00:00',
}

function issueFixture(status: 'draft' | 'published') {
  return {
    issueKey: '2026-09-18',
    status,
    title: '测试日报',
    sections: [
      { heading: '要点', items: [{ summary: '一条总结。', sourceIds: ['s1'], uncertainty: null }] },
    ],
    refs: {
      s1: { title: 'T', url: 'https://a.example.com/x', feedTitle: 'F', publishedAt: '2026-09-18T00:00:00+00:00' },
    },
    model: 'm',
    meta: {},
    sentenceMap: [{ sentence: '一条总结。', refs: ['s1'], verified: true }],
    note: '',
    revised: false,
    createdAt: '2026-09-18T00:00:00+00:00',
    publishedAt: '2026-09-18T00:00:00+00:00',
    updatedAt: '2026-09-18T00:00:00+00:00',
  }
}

const PREVIEW = {
  windowStart: '2026-09-17T08:00:00Z',
  windowEnd: '2026-09-18T08:00:00Z',
  selected: [
    { sourceId: 's1', title: '文章一', feedTitle: '来源一', source: 'window' },
    { sourceId: 's2', title: '文章二', feedTitle: '来源二', source: 'manual' },
  ],
  counts: { total: 5, selected: 2, outsideWindow: 1, duplicate: 1, recentIssue: 1 },
  perSource: { 来源一: 1 },
  coveredSources: [],
  missingSources: [],
  excludedRecent: [
    { url: 'https://a.example.com/old', title: '昨日已刊', feedTitle: '来源一', issueKey: '2026-09-17' },
  ],
  poolInvalid: [],
  note: '窗口内入选 2 条。',
}

function baseHandler(url: string, init?: RequestInit): Response | Promise<Response> {
  if (url.endsWith('/gpt-digest/configs') && (!init || !init.method)) {
    return jsonResponse({ items: [CONFIG] })
  }
  if (/\/configs\/1\/issues(\?|$)/.test(url)) {
    return jsonResponse({ items: [issueFixture('draft')] })
  }
  if (/\/configs\/\d+\/pool$/.test(url) && (!init?.method || init.method === 'GET')) {
    return jsonResponse({ items: [], used: [] })
  }
  if (/\/configs\/\d+\/missing-dates/.test(url)) {
    return jsonResponse({ missing: [], existing: ['2026-09-18'] })
  }
  if (/\/configs\/\d+\/feed/.test(url)) {
    return jsonResponse({ atomPath: '/feeds/gpt-digest/x.atom' })
  }
  throw new Error(`unexpected fetch: ${url} ${init?.method ?? 'GET'}`)
}

function renderSection(handler?: typeof baseHandler) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) =>
    (handler ?? baseHandler)(String(input), init),
  )
  vi.stubGlobal('fetch', fetchMock)
  render(
    <QueryClientProvider client={qc}>
      <GptDigestSection />
    </QueryClientProvider>,
  )
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

/** 配置面两层：高级区默认折叠，断言前先展开。 */
async function openAdvanced() {
  fireEvent.click(await screen.findByRole('button', { name: '高级设置' }))
}

describe('配置面两层结构', () => {
  it('基础层默认可见（时间范围/上限/长度/发布时间/时区/预览/生成）；高级层默认折叠', async () => {
    renderSection()
    await screen.findByLabelText('选择日报配置')
    // 基础层旋钮与操作默认在文档中
    expect(screen.getByLabelText('选材窗口小时')).toBeInTheDocument()
    expect(screen.getByLabelText('单期条目上限')).toBeInTheDocument()
    expect(screen.getByLabelText('目标阅读时长分钟')).toBeInTheDocument()
    expect(screen.getByLabelText('发布小时')).toBeInTheDocument()
    expect(screen.getByLabelText('时区')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '预览选材' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '生成今日日报' })).toBeInTheDocument()
    // 高级层旋钮默认不在文档中（折叠）
    expect(screen.queryByLabelText('单一来源占比上限')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('回看去重天数')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('发布时点列表')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('选材模型')).not.toBeInTheDocument()
    // 展开后高级层可见
    await openAdvanced()
    expect(screen.getByLabelText('单一来源占比上限')).toBeInTheDocument()
    expect(screen.getByLabelText('回看去重天数')).toBeInTheDocument()
    expect(screen.getByLabelText('发布时点列表')).toBeInTheDocument()
    expect(screen.getByLabelText('选材模型')).toBeInTheDocument()
  })
})

describe('生成流程：阶段进度 + 取消 + 重试', () => {
  it('生成期间轮询 run-status 显示服务端真实阶段；停止后在阶段边界生效且可重新生成', async () => {
    let resolveGenerate!: (response: Response) => void
    const fetchMock = renderSection((url, init) => {
      const u = String(url)
      if (/\/configs\/1\/generate$/.test(u) && init?.method === 'POST') {
        return new Promise<Response>((resolve) => {
          resolveGenerate = resolve
        })
      }
      if (/\/configs\/1\/run-status$/.test(u)) {
        return jsonResponse({ running: true, stage: 'select', startedAt: '2026-10-02T08:00:00+00:00' })
      }
      if (/\/configs\/1\/cancel$/.test(u) && init?.method === 'POST') {
        return jsonResponse({ cancelled: true })
      }
      return baseHandler(url, init)
    })
    await screen.findByLabelText('选择日报配置')
    fireEvent.click(screen.getByRole('button', { name: '生成今日日报' }))
    // 阶段进度来自服务端 run-status（选题），不虚构百分比
    expect(await screen.findByText(/阶段：选题/)).toBeInTheDocument()
    expect(
      fetchMock.mock.calls.some(([u]) => String(u).endsWith('/configs/1/run-status')),
    ).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: '停止生成' }))
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([u, i]) => String(u).endsWith('/configs/1/cancel') && i?.method === 'POST',
        ),
      ).toBe(true)
    })
    // 服务端以 409 cancelled 收尾（协作式取消：绝不半写期号）
    resolveGenerate(
      jsonResponse({ error: { type: 'cancelled', message: '已停止本次生成；未写入任何期号。' } }, 409),
    )
    expect(await screen.findByText(/已停止生成/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重新生成' })).toBeInTheDocument()
  })

  it('生成失败透出稳定错误并展示重试生成入口', async () => {
    renderSection((url, init) => {
      if (/\/configs\/1\/generate$/.test(String(url)) && init?.method === 'POST') {
        return jsonResponse(
          { error: { type: 'ai_not_configured', message: 'AI 未配置或配置不可用（详见设置）。' } },
          409,
        )
      }
      return baseHandler(url, init)
    })
    await screen.findByLabelText('选择日报配置')
    fireEvent.click(screen.getByRole('button', { name: '生成今日日报' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('AI 未配置或配置不可用')
    expect(screen.getByRole('button', { name: '重试生成' })).toBeInTheDocument()
  })
})

describe('预览 → 草稿 → 审阅发布（两步）', () => {
  it('预览无副作用渲染选材；发布草稿仅请求 publish 且行内状态即时更新', async () => {
    let published = false
    const fetchMock = renderSection((url, init) => {
      const u = String(url)
      if (/\/configs\/1\/preview$/.test(u)) {
        return jsonResponse(PREVIEW)
      }
      if (/\/configs\/1\/issues\/2026-09-18\/publish$/.test(u) && init?.method === 'POST') {
        published = true
        return jsonResponse({ issue: issueFixture('published') })
      }
      if (/\/configs\/1\/issues(\?|$)/.test(u)) {
        return jsonResponse({ items: [issueFixture(published ? 'published' : 'draft')] })
      }
      return baseHandler(url, init)
    })
    await screen.findByLabelText('选择日报配置')
    // 草稿两步：先出现草稿徽标与「审阅并发布」
    expect(await screen.findByText('草稿')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '预览选材' }))
    expect(await screen.findByText(/文章一/)).toBeInTheDocument()
    expect(screen.getByText(/文章二/)).toBeInTheDocument()
    expect(screen.getByText('素材池')).toBeInTheDocument() // manual 候选标注
    expect(screen.getByText(/近期已刊用（1/)).toBeInTheDocument()
    // 第二步：审阅并发布（幂等 POST；响应 DTO 即时反映已发布）
    fireEvent.click(screen.getByRole('button', { name: '审阅并发布' }))
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([u, i]) =>
            String(u).endsWith('/issues/2026-09-18/publish') && i?.method === 'POST',
        ),
      ).toBe(true)
    })
    await waitFor(() => {
      expect(screen.getByText('已发布')).toBeInTheDocument()
    })
    expect(screen.queryByText('草稿')).not.toBeInTheDocument()
  })
})

describe('文案与 aria 无 GPT 字样', () => {
  it('完整渲染（含高级区）后，可见文本与 aria-label 不含 "GPT"', async () => {
    renderSection()
    await screen.findByLabelText('选择日报配置')
    await openAdvanced()
    // 订阅地址（旧路由 /feeds/gpt-digest/…）为兼容保留且为小写；此处
    // 断言的是用户文案/aria 层面不出现大写 "GPT"。
    expect(document.body.textContent).not.toMatch(/GPT/)
    const offenders = Array.from(document.querySelectorAll('[aria-label]')).filter((el) =>
      /GPT/.test(el.getAttribute('aria-label') ?? ''),
    )
    expect(offenders).toEqual([])
  })
})
