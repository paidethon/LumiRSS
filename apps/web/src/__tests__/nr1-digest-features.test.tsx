/** N171–N176：日报增强功能设置 UI 行为测试。
 *
 * 断言 DOM 语义与交互：N171 发布日/周末时点、N172 分阶段模型 +
 * 润色失败重试、N173 事实检查视图（待核实标注 + 逐句删除）、
 * N174 栏目结构、N175 目标阅读时长（素材篮 + 裁剪预览）、
 * N176 同事件聚合开关。fetch 全部 stub，绝不触网。 */

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
  lastIssueKey: '2026-09-18',
  lastError: null,
  createdAt: '2026-09-18T00:00:00+00:00',
}

const ISSUE = {
  issueKey: '2026-09-18',
  status: 'published',
  title: '测试日报',
  sections: [
    { heading: '要点', items: [{ summary: '甲句内容。乙句改写。', sourceIds: ['s1'], uncertainty: null }] },
  ],
  refs: {
    s1: { title: 'T', url: 'https://a.example.com/x', feedTitle: 'F', publishedAt: '2026-09-18T00:00:00+00:00' },
  },
  model: 'm',
  meta: {
    stageModels: { summarize: 'm-sum' },
    polishFailed: true,
    polishError: '润色阶段（polish）调用失败：上游超时',
    leftoverPool: [
      {
        sectionHeading: '要点',
        summary: '被裁剪的条目总结。',
        sourceIds: ['s2'],
        refs: [{ title: 'T2', url: 'https://a.example.com/y', feedTitle: 'F2' }],
      },
    ],
  },
  sentenceMap: [
    { sentence: '甲句内容。', refs: ['s1'], verified: true },
    { sentence: '乙句改写。', refs: [], verified: false },
  ],
  createdAt: '2026-09-18T00:00:00+00:00',
  publishedAt: '2026-09-18T00:00:00+00:00',
  updatedAt: '2026-09-18T00:00:00+00:00',
}

function baseHandler(url: string, init?: RequestInit): Response | Promise<Response> {
  if (url.endsWith('/gpt-digest/configs') && (!init || !init.method)) {
    return jsonResponse({ items: [CONFIG] })
  }
  if (url.endsWith('/issues?limit=14') || /\/configs\/\d+\/issues$/.test(url)) {
    return jsonResponse({ items: [ISSUE] })
  }
  if (/\/configs\/\d+\/pool$/.test(url) && (!init?.method || init.method === 'GET')) {
    return jsonResponse({ items: [], used: [] })
  }
  if (/\/configs\/\d+\/missing-dates/.test(url)) {
    return jsonResponse({ missing: [], existing: [] })
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

describe('N171 发布日与周末时点', () => {
  it('发布日可切换并进入保存载荷（含周末独立时点）', async () => {
    const fetchMock = renderSection((url, init) => {
      if (url.endsWith('/gpt-digest/configs/1') && init?.method === 'PUT') {
        return jsonResponse(CONFIG)
      }
      return baseHandler(url, init)
    })
    const saturday = await screen.findByLabelText('发布日 周六')
    fireEvent.click(saturday)
    fireEvent.change(screen.getByLabelText('周末发布时点'), { target: { value: '10,16' } })
    fireEvent.click(screen.getByRole('button', { name: '保存设置' }))
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        ([url, init]) => String(url).endsWith('/configs/1') && init?.method === 'PUT',
      )
      expect(put).toBeTruthy()
      const body = JSON.parse(String(put?.[1]?.body))
      expect(body.days).toEqual([5])
      expect(body.weekendHours).toEqual([10, 16])
    })
  })
})

describe('N172 分阶段模型与重试润色', () => {
  it('阶段模型进入保存载荷（空阶段不发送）', async () => {
    const fetchMock = renderSection((url, init) => {
      if (url.endsWith('/gpt-digest/configs/1') && init?.method === 'PUT') {
        return jsonResponse(CONFIG)
      }
      return baseHandler(url, init)
    })
    fireEvent.change(await screen.findByLabelText('润色模型'), { target: { value: 'm-polish' } })
    fireEvent.click(screen.getByRole('button', { name: '保存设置' }))
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        ([url, init]) => String(url).endsWith('/configs/1') && init?.method === 'PUT',
      )
      const body = JSON.parse(String(put?.[1]?.body))
      expect(body.stageModels).toEqual({ polish: 'm-polish' })
    })
  })

  it('润色失败显示重试入口；点击仅请求 retry-polish', async () => {
    const fetchMock = renderSection((url, init) => {
      if (url.endsWith('/retry-polish') && init?.method === 'POST') {
        return jsonResponse({ issue: { ...ISSUE, meta: { stageModels: { polish: 'm' } } } })
      }
      return baseHandler(url, init)
    })
    expect(await screen.findByText(/润色失败/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重试润色' }))
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url, init]) => String(url).endsWith('/retry-polish') && init?.method === 'POST'),
      ).toBe(true)
    })
  })

  it('分阶段模型标签按阶段展示', async () => {
    renderSection()
    expect(await screen.findByText(/模型（按阶段）：summarize=m-sum/)).toBeInTheDocument()
  })
})

describe('N173 事实检查视图', () => {
  it('逐句展示；人工改写句标注待核实', async () => {
    renderSection()
    fireEvent.click(await screen.findByRole('button', { name: '事实检查' }))
    const verified = await screen.findByText('甲句内容。')
    expect(verified).toBeInTheDocument()
    expect(screen.getByText('待核实')).toBeInTheDocument()
    expect(screen.getByText(/已核对（s1）/)).toBeInTheDocument()
  })

  it('删除句子发出逐句操作（sentenceOps）', async () => {
    const fetchMock = renderSection((url, init) => {
      if (/\/configs\/1\/issues\/2026-09-18$/.test(url) && init?.method === 'PUT') {
        return jsonResponse({ issue: ISSUE })
      }
      return baseHandler(url, init)
    })
    await screen.findByText(/测试日报/)
    fireEvent.click(screen.getByRole('button', { name: '事实检查' }))
    const deleteButtons = await screen.findAllByRole('button', { name: /^删除句子：/ })
    fireEvent.click(deleteButtons[0])
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        ([url, init]) => /\/configs\/1\/issues\/2026-09-18$/.test(String(url)) && init?.method === 'PUT',
      )
      expect(put).toBeTruthy()
      const body = JSON.parse(String(put?.[1]?.body))
      expect(body.sentenceOps).toEqual([
        { op: 'delete', sectionIndex: 0, itemIndex: 0, sentenceIndex: 0 },
      ])
    })
  })
})

describe('N174/N175/N176 栏目、阅读时长与聚合', () => {
  it('栏目结构按行解析进入保存载荷', async () => {
    const fetchMock = renderSection((url, init) => {
      if (url.endsWith('/gpt-digest/configs/1') && init?.method === 'PUT') {
        return jsonResponse(CONFIG)
      }
      return baseHandler(url, init)
    })
    fireEvent.change(await screen.findByLabelText('固定栏目结构'), {
      target: { value: '人工智能|5|placeholder\n开源|3|hide' },
    })
    fireEvent.click(screen.getByRole('button', { name: '保存设置' }))
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        ([url, init]) => String(url).endsWith('/configs/1') && init?.method === 'PUT',
      )
      const body = JSON.parse(String(put?.[1]?.body))
      expect(body.columns).toEqual([
        { name: '人工智能', count: 5, emptyPolicy: 'placeholder' },
        { name: '开源', count: 3, emptyPolicy: 'hide' },
      ])
    })
  })

  it('目标阅读时长与同事件聚合进入保存载荷', async () => {
    const fetchMock = renderSection((url, init) => {
      if (url.endsWith('/gpt-digest/configs/1') && init?.method === 'PUT') {
        return jsonResponse(CONFIG)
      }
      return baseHandler(url, init)
    })
    fireEvent.change(await screen.findByLabelText('目标阅读时长分钟'), { target: { value: '30' } })
    fireEvent.click(screen.getByRole('switch', { name: /同事件聚合 默认日报/ }))
    fireEvent.click(screen.getByRole('button', { name: '保存设置' }))
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        ([url, init]) => String(url).endsWith('/configs/1') && init?.method === 'PUT',
      )
      const body = JSON.parse(String(put?.[1]?.body))
      expect(body.targetReadingMinutes).toBe(30)
      expect(body.clusterEnabled).toBe(true)
    })
  })

  it('素材篮展示被移出的条目（未删除）', async () => {
    renderSection()
    expect(await screen.findByText(/素材篮（1 条因阅读时长预算移出，未删除）/)).toBeInTheDocument()
    expect(screen.getByText(/被裁剪的条目总结。/)).toBeInTheDocument()
  })

  it('裁剪预览按需拉取并显示 before/after', async () => {
    const fetchMock = renderSection((url, init) => {
      if (/\/trim-preview$/.test(url)) {
        return jsonResponse({
          targetReadingMinutes: 1,
          beforeMinutes: 2.5,
          afterMinutes: 0.75,
          moved: [{ sectionHeading: '要点', summary: '将被移出的长条目。', sourceIds: ['s1'], refs: [] }],
          note: '将移出 1 条进素材篮（估算约 2.5 → 0.75 分钟）。',
        })
      }
      return baseHandler(url, init)
    })
    await screen.findByText(/测试日报/)
    fireEvent.click(screen.getByRole('button', { name: '裁剪预览' }))
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) => /\/trim-preview$/.test(String(url))),
      ).toBe(true)
    })
    expect(await screen.findByText(/2\.5 → 0\.75 分钟/)).toBeInTheDocument()
    expect(screen.getByText(/将被移出的长条目。/)).toBeInTheDocument()
  })
})
