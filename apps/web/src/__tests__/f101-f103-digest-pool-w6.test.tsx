/** F101/F102/F103 —— W6 日报域 Web 层。
 *
 * F101：选材预览的「近期已刊用」明细与单条放回（putBack 重跑预览）；
 * F102：素材池面板（按 ref 加入 / 409 诚实报错 / 排序 PATCH / 移除 /
 * 已刊用分列）；F103：订阅 token 轮换两步（dry-run 影响确认 → 执行 →
 * 新地址一次性展示）。fetch 全部 stub，绝不触网。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { GptDigestSection } from '../components/settings/GptDigestSection'

const CONFIG = {
  id: 1,
  name: '默认日报',
  enabled: true,
  hour: 8,
  timezone: '',
  windowHours: 24,
  limitCount: 12,
  perSourceCap: 2,
  feedUrlAllow: '',
  sourceKind: 'window',
  lookbackDays: 7,
  slots: [],
  lastIssueKey: null,
  lastError: null,
  createdAt: '2026-09-18T00:00:00+00:00',
}

const CONFIGS = { items: [CONFIG] }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function baseHandler(url: string, init?: RequestInit): Response {
  if (url.endsWith('/gpt-digest/configs') && (!init || init.method === undefined)) {
    return jsonResponse(CONFIGS)
  }
  if (/\/configs\/1\/issues/.test(url)) return jsonResponse({ items: [] })
  if (/\/configs\/1\/feed$/.test(url)) return jsonResponse({ atomPath: '/feeds/gpt-digest/tok.atom' })
  if (/\/configs\/1\/missing-dates/.test(url)) return jsonResponse({ missing: [], existing: [] })
  if (/\/configs\/1\/pool$/.test(url) && (init?.method === undefined || init.method === 'GET')) {
    return jsonResponse({ items: [], used: [] })
  }
  console.warn('unexpected fetch:', url, init?.method ?? 'GET')
  throw new Error(`unexpected fetch: ${url} ${init?.method ?? 'GET'}`)
}

function renderSection(handler?: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
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

function qs(attr: string): HTMLElement {
  const el = document.querySelector(`[${attr}]`)
  if (el === null) throw new Error(`missing ${attr}`)
  return el as HTMLElement
}
function qsq(attr: string): HTMLElement | null {
  return document.querySelector(`[${attr}]`)
}
function findByPreviewPanel(): Promise<HTMLElement> {
  return waitFor(() => qs('data-lumi-excluded-recent'), { timeout: 3000, interval: 50 })
}
function queryPreviewExcluded(): HTMLElement | null {
  return qsq('data-lumi-excluded-recent')
}
function poolList(): HTMLElement {
  return qs('data-lumi-pool-list')
}
function poolEmpty(): HTMLElement {
  return qs('data-lumi-pool-empty')
}
function poolUsed(): HTMLElement {
  return qs('data-lumi-pool-used')
}
function rotateConfirm(): Promise<HTMLElement> {
  return waitFor(() => qs('data-lumi-digest-rotate-confirm'), { timeout: 3000, interval: 50 })
}
function queryRotateConfirm(): HTMLElement | null {
  return qsq('data-lumi-digest-rotate-confirm')
}
function rotateDone(): Promise<HTMLElement> {
  return waitFor(() => qs('data-lumi-digest-rotate-done'), { timeout: 3000, interval: 50 })
}

describe('F101 选材预览：近期已刊用标记与放回', () => {
  it('F101: 预览渲染「近期已刊用」明细；放回后以 putBack 重跑预览', async () => {
    const previewCalls: string[] = []
    const fetchMock = renderSection((url, init) => {
      if (/\/configs\/1\/preview/.test(url) && (!init?.method || init.method === 'GET')) {
        previewCalls.push(url)
        const first = previewCalls.length === 1
        return jsonResponse({
          windowStart: '2026-09-14T00:00:00+00:00',
          windowEnd: '2026-09-15T00:00:00+00:00',
          selected: first
            ? [{ sourceId: 's1', title: '新文', feedTitle: '源A', feedUrl: 'https://a/rss', url: 'https://a/1', publishedAt: '2026-09-14T10:00:00Z', source: 'auto' }]
            : [
                { sourceId: 's1', title: '新文', feedTitle: '源A', feedUrl: 'https://a/rss', url: 'https://a/1', publishedAt: '2026-09-14T10:00:00Z', source: 'auto' },
                { sourceId: 's2', title: '旧文A', feedTitle: '源A', feedUrl: 'https://a/rss', url: 'https://a/old', publishedAt: '2026-09-14T11:00:00Z', source: 'auto' },
              ],
          counts: { recentIssue: first ? 1 : 0 },
          perSource: {},
          coveredSources: [],
          missingSources: [],
          excludedRecent: first
            ? [{ title: '旧文A', feedTitle: '源A', url: 'https://a/old', reason: 'recent_issue' }]
            : [],
          poolInvalid: [],
          note: '预览即所得',
        })
      }
      return baseHandler(url, init)
    })

    await screen.findByLabelText('选择日报配置')
    fireEvent.click(await screen.findByRole('button', { name: '预览选材' }))
    const badge = await findByPreviewPanel()
    expect(badge.textContent).toContain('近期已刊用')
    expect(badge.textContent).toContain('旧文A')

    // 放回：以材料身份 url:https://a/old 重跑预览
    fireEvent.click(screen.getByRole('button', { name: '放回本次' }))
    await waitFor(() => {
      expect(previewCalls.some((call) => call.includes('putBack=url%3Ahttps%3A%2F%2Fa%2Fold'))).toBe(true)
    })
    await waitFor(() => {
      expect(queryPreviewExcluded()).not.toBeInTheDocument()
    })
    expect(fetchMock).toHaveBeenCalled()
  })

  it('F101: 保存设置发出 lookbackDays；改 0 = 关闭去重', async () => {
    const fetchMock = renderSection((url, init) => {
      if (url.endsWith('/gpt-digest/configs/1') && init?.method === 'PUT') {
        return jsonResponse({ ...CONFIG, lookbackDays: 0 })
      }
      return baseHandler(url, init)
    })
    await screen.findByLabelText('选择日报配置')
    const input = await screen.findByLabelText('回看去重天数')
    fireEvent.change(input, { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: '保存设置' }))
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        ([url, init]) => String(url).endsWith('/configs/1') && init?.method === 'PUT',
      )
      expect(put).toBeDefined()
      expect(JSON.parse(String(put?.[1]?.body)).lookbackDays).toBe(0)
    })
  })
})

describe('F102 素材池面板', () => {
  it('F102: 按 ref 加入（201）；重复 409 诚实报错；列表渲染与移除', async () => {
    let poolItems: { id: number; entryRef: string; addedAt: string; position: number; usedIssueKey: string | null }[] = []
    let nextId = 2
    const fetchMock = renderSection((url, init) => {
      if (/\/configs\/1\/pool$/.test(url)) {
        const method = init?.method ?? 'GET'
        if (method === 'GET') return jsonResponse({ items: poolItems, used: [] })
        if (method === 'POST') {
          const body = JSON.parse(String(init?.body)) as { entryRef: string }
          if (poolItems.some((entry) => entry.entryRef === body.entryRef)) {
            return jsonResponse({ error: { type: 'duplicate', message: '该条目已在素材池中。' } }, 409)
          }
          const entry = { id: nextId++, entryRef: body.entryRef, addedAt: '2026-09-19T00:00:00Z', position: poolItems.length, usedIssueKey: null }
          poolItems = [...poolItems, entry]
          return jsonResponse(entry, 201)
        }
      }
      if (/\/configs\/1\/pool\/\d+$/.test(url) && init?.method === 'DELETE') {
        const id = Number(url.split('/').pop())
        poolItems = poolItems.filter((entry) => entry.id !== id)
        return new Response(null, { status: 204 })
      }
      return baseHandler(url, init)
    })

    await screen.findByLabelText('选择日报配置')
    const input = await screen.findByLabelText('按条目引用加入素材池')
    fireEvent.change(input, { target: { value: 'rss:abc' } })
    fireEvent.click(screen.getByRole('button', { name: '加入日报待编' }))
    await waitFor(() => {
      expect(poolList().textContent).toContain('rss:abc')
    })

    // 重复加入 → 409 消息诚实透出
    fireEvent.change(input, { target: { value: 'rss:abc' } })
    fireEvent.click(screen.getByRole('button', { name: '加入日报待编' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('该条目已在素材池中。')

    // 移除
    fireEvent.click(screen.getByRole('button', { name: '移出素材池 rss:abc' }))
    await waitFor(() => {
      expect(poolEmpty()).toBeInTheDocument()
    })
    const del = fetchMock.mock.calls.find(([url, init]) => /\/pool\/\d+$/.test(String(url)) && init?.method === 'DELETE')
    expect(del).toBeDefined()
  })

  it('F102: 上移发出 PATCH orderedIds；已刊用分列展示', async () => {
    const pool = {
      items: [
        { id: 11, entryRef: 'rss:a', addedAt: '', position: 0, usedIssueKey: null },
        { id: 22, entryRef: 'rss:b', addedAt: '', position: 1, usedIssueKey: null },
      ],
      used: [{ id: 33, entryRef: 'rss:c', addedAt: '', position: 2, usedIssueKey: '2026-09-18' }],
    }
    const fetchMock = renderSection((url, init) => {
      const method = init?.method
      if (/\/configs\/1\/pool$/.test(url) && (method === undefined || method === 'GET')) {
        return jsonResponse({ items: pool.items, used: pool.used })
      }
      if (/\/configs\/1\/pool$/.test(url) && method === 'PATCH') {
        const body = JSON.parse(String(init?.body)) as { orderedIds: number[] }
        const ordered = body.orderedIds
          .map((id) => pool.items.find((entry) => entry.id === id))
          .filter((entry) => entry !== undefined)
        return jsonResponse({ items: ordered })
      }
      return baseHandler(url, init)
    })
    await screen.findByLabelText('选择日报配置')
    expect((await screen.findByText('素材池（手工候选）'))).toBeInTheDocument()
    await waitFor(() => expect(poolList().textContent).toContain('rss:a'))
    expect(poolUsed().textContent).toContain('期号 2026-09-18')

    fireEvent.click(screen.getByRole('button', { name: '上移 rss:b' }))
    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')
      expect(patch).toBeDefined()
      expect(JSON.parse(String(patch?.[1]?.body)).orderedIds).toEqual([22, 11])
    })
  })
})

describe('F103 订阅 token 轮换两步', () => {
  it('F103: 轮换先 dry-run 展示影响，确认后才执行并展示新地址', async () => {
    const fetchMock = renderSection((url, init) => {
      if (url.includes('/gpt-digest/feed/rotate?dryRun=true')) {
        return jsonResponse({
          dryRun: true,
          impact: { tokenExists: true, tokenRotatedAt: '2026-09-01T00:00:00+00:00', ageDays: 18, note: '轮换后旧链接立即失效；订阅方需更新。' },
        })
      }
      if (url.endsWith('/gpt-digest/feed/rotate') && init?.method === 'POST') {
        return jsonResponse({ atomPath: '/feeds/gpt-digest/newtok.atom' })
      }
      return baseHandler(url, init)
    })

    await screen.findByLabelText('选择日报配置')
    fireEvent.click(await screen.findByRole('button', { name: '轮换 token' }))

    // 第一步：影响确认（dry-run，未执行轮换）
    const confirm = await rotateConfirm()
    expect(confirm.textContent).toContain('确认轮换订阅 token？')
    await waitFor(() => expect(confirm.textContent).toContain('18 天前'))
    expect(
      fetchMock.mock.calls.some(([url, init]) => String(url).includes('dryRun=true') && init?.method === 'POST'),
    ).toBe(true)
    expect(
      fetchMock.mock.calls.some(([url, init]) => String(url).endsWith('/gpt-digest/feed/rotate') && init?.method === 'POST'),
    ).toBe(false)

    // 取消 → 不轮换
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(queryRotateConfirm()).not.toBeInTheDocument()

    // 再走一次并确认 → 执行
    fireEvent.click(screen.getByRole('button', { name: '轮换 token' }))
    fireEvent.click(await screen.findByRole('button', { name: '确认轮换' }))
    const done = await rotateDone()
    expect(done.textContent).toContain('旧地址已失效')
    expect(done.textContent).toContain('newtok.atom')
  })

  it('F103: dry-run 后取消不触发轮换端点（第二次确认路径幂等可见）', async () => {
    const fetchMock = renderSection((url, init) => {
      if (url.includes('/gpt-digest/feed/rotate?dryRun=true')) {
        return jsonResponse({
          dryRun: true,
          impact: { tokenExists: true, tokenRotatedAt: null, ageDays: null, note: '轮换后旧链接立即失效；订阅方需更新。' },
        })
      }
      return baseHandler(url, init)
    })
    await screen.findByLabelText('选择日报配置')
    fireEvent.click(await screen.findByRole('button', { name: '轮换 token' }))
    await rotateConfirm()
    // 无记录 → 诚实显示「时间未知」，不编造
    await waitFor(() => expect(queryRotateConfirm()?.textContent ?? '').toContain('时间未知'))
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(
      fetchMock.mock.calls.some(([url, init]) => String(url).endsWith('/gpt-digest/feed/rotate') && init?.method === 'POST'),
    ).toBe(false)
  })
})
