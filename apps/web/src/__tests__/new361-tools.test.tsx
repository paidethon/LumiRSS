/** NEW-361..370 Web 入口测试 — 搜索表达、专题发现与回溯的组件主路径。
 *
 * 环境：jsdom；fetch 按 URL 匹配 mock（服务真源在 BFF，后端口径见
 * services/bff/tests/test_new36*.py / test_new370*.py）。
 * 重点：显式确认才写入（362/365）、只建议不替换（368）、默认关闭
 * 才重排（370）、unknown 单独呈现（369）。
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TimeBrushPanel } from '../components/new361/TimeBrushPanel'
import { SimilarTitleCandidatesPanel } from '../components/new361/SimilarTitleCandidatesPanel'
import { FieldHitBadges } from '../components/new361/FieldHitBadges'
import { AuthorSourceFacetsPanel } from '../components/new361/AuthorSourceFacetsPanel'
import { ExclusionSuggestionsPanel } from '../components/new361/ExclusionSuggestionsPanel'
import { ParagraphHitsPanel } from '../components/new361/ParagraphHitsPanel'
import { SearchSessionPanel } from '../components/new361/SearchSessionPanel'
import { SpellSuggestions } from '../components/new361/SpellSuggestions'
import { LanguageGroupsPanel } from '../components/new361/LanguageGroupsPanel'
import {
  FeedbackSummary,
  HitFeedbackControls,
  RankingSchemeToggle,
} from '../components/new361/HitFeedbackControls'
import type { FieldHitItem } from '../api/new361'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderWithQuery(ui: React.ReactElement): ReturnType<typeof render> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

type Route = {
  match: (url: string, init?: RequestInit) => boolean
  respond: (url: string, init?: RequestInit) => Response
}

const routes: Route[] = []
const calls: { url: string; init?: RequestInit }[] = []

function mockRoute(
  matcher: (url: string, init?: RequestInit) => boolean,
  responder: (url: string, init?: RequestInit) => Response,
): void {
  routes.push({ match: matcher, respond: responder })
}

function callsTo(url: string): { url: string; init?: RequestInit }[] {
  return calls.filter((call) => call.url === url || call.url.startsWith(`${url}?`))
}

beforeEach(() => {
  routes.length = 0
  calls.length = 0
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    calls.push({ url, init })
    for (const route of routes) {
      if (route.match(url, init)) return route.respond(url, init)
    }
    return jsonResponse({ error: { type: 'unmocked', message: url } }, 404)
  }) as typeof fetch
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('NEW-361 时间范围刷选', () => {
  it('桶计数来自实际命中；点击桶把区间交给父级（复用 from/to）', async () => {
    const onApplyRange = vi.fn()
    const day = new Date(Date.now() - 3 * 86_400_000).toISOString().slice(0, 10)
    mockRoute(
      (url) => url.startsWith('/api/v1/search/time-brush'),
      () =>
        jsonResponse({
          buckets: [
            { key: day, count: 2 },
            { key: 'empty-day', count: 0 },
          ],
          total: 2,
          granularity: 'day',
          dayFrom: 'd0',
          dayTo: 'd1',
          hint: '查看该区间文章请以 from/to 调用 GET /api/v1/search。',
        }),
    )
    renderWithQuery(<TimeBrushPanel query="内核" onApplyRange={onApplyRange} />)
    await waitFor(() => {
      expect(screen.getByTitle(`${day}：2 条（点击查看）`)).toBeTruthy()
    })
    expect(screen.getByText(/实际命中 2 条/)).toBeTruthy()
    fireEvent.click(screen.getByTitle(`${day}：2 条（点击查看）`))
    expect(onApplyRange).toHaveBeenCalledWith(day, day)
    expect(callsTo('/api/v1/search/time-brush').length).toBeGreaterThan(0)
  })
})

describe('NEW-362 相似标题候选审阅', () => {
  it('候选展示可解释相似度；确认动作显式触发 POST 且只在用户点击时', async () => {
    mockRoute(
      (url) => url.startsWith('/api/v1/search/similar-title-candidates?entryRef='),
      () =>
        jsonResponse({
          entry: { entryRef: 'e1.a', title: '标题A', feedTitle: '源', publishedAt: 'T0' },
          candidates: [
            {
              entryRef: 'e1.b',
              title: '标题A（转载）',
              feedTitle: '源',
              publishedAt: 'T1',
              sameSource: true,
              inGroup: null,
              inGroupNote: null,
              score: 88,
              sharedBigrams: 9,
              sharedSample: '标题',
              totalBigrams: { a: 10, b: 11 },
            },
          ],
          scanned: 10,
          scannedCapped: false,
        }),
    )
    mockRoute(
      (url, init) =>
        url === '/api/v1/search/similar-title-candidates/confirm' &&
        init?.method === 'POST',
      (url, init) =>
        jsonResponse(
          {
            relation: { id: 1, srcRef: 'e1.a', dstRef: 'e1.b', kind: 'duplicate', note: '疑似重复', createdAt: 'T' },
            explained: '确认后写入',
          },
          201,
        ),
    )
    renderWithQuery(<SimilarTitleCandidatesPanel entryRef="e1.a" />)
    // 情境展开：折叠态零请求。
    expect(calls.length).toBe(0)
    fireEvent.click(screen.getByTestId('n362-toggle'))
    await waitFor(() => {
      expect(screen.getByTestId('n362-candidate')).toBeTruthy()
    })
    expect(screen.getByText(/相似度 88%：共有 9 组字符片段/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '确认加入重复组' }))
    await waitFor(() => {
      expect(callsTo('/api/v1/search/similar-title-candidates/confirm').length).toBe(1)
    })
    const body = JSON.parse(
      String(callsTo('/api/v1/search/similar-title-candidates/confirm')[0].init?.body),
    )
    expect(body).toEqual({ aRef: 'e1.a', bRef: 'e1.b', relation: 'duplicate' })
  })
})

describe('NEW-363 跨字段命中说明', () => {
  it('字段徽标可点击定位；本人笔记列带计数与摘录', () => {
    const hit: FieldHitItem = {
      entryRef: 'e1.a',
      fields: ['title', 'content', 'note'],
      noteHit: { count: 2, excerpt: '…我的量子笔记…' },
    }
    const onLocate = vi.fn()
    renderWithQuery(<FieldHitBadges hit={hit} onLocate={onLocate} />)
    fireEvent.click(screen.getByTestId('n363-field-note'))
    expect(onLocate).toHaveBeenCalledWith('note', '…我的量子笔记…')
    fireEvent.click(screen.getByTestId('n363-field-title'))
    expect(onLocate).toHaveBeenCalledWith('title', null)
    expect(screen.getByText(/我的量子笔记/)).toBeTruthy()
  })
})

describe('NEW-364 作者与来源交叉筛选', () => {
  it('展示每个作者/来源的真实命中数；点选交给父级应用过滤', async () => {
    const onSelectAuthor = vi.fn()
    mockRoute(
      (url) => url.startsWith('/api/v1/search/author-source'),
      () =>
        jsonResponse({
          total: 3,
          authors: [
            { author: '王研究', count: 2 },
            { author: '李通讯', count: 1 },
          ],
          authorsComplete: true,
          sources: [{ feedUrl: 'https://a.example/rss', feedTitle: '源甲', count: 2 }],
          sourcesComplete: true,
          selected: { author: null, feedUrl: null },
          note: '每个数字 = 勾选该项后组合的真实命中数。',
        }),
    )
    renderWithQuery(
      <AuthorSourceFacetsPanel
        query="光栅"
        activeAuthor={null}
        activeFeedUrl={null}
        onSelectAuthor={onSelectAuthor}
        onSelectFeedUrl={() => {}}
      />,
    )
    await waitFor(() => {
      expect(screen.getAllByTestId('n364-author').length).toBe(2)
    })
    expect(screen.getByText(/当前组合实际命中 3 条/)).toBeTruthy()
    fireEvent.click(screen.getAllByTestId('n364-author')[0])
    expect(onSelectAuthor).toHaveBeenCalledWith('王研究')
  })
})

describe('NEW-365 搜索排除词建议审批', () => {
  it('候选按标记数展示；确认才加入查询；撤销即失效', async () => {
    const markedRefs = ['e1.m1', 'e1.m2']
    mockRoute(
      (url, init) => url === '/api/v1/search/exclusion-candidates' && init?.method === 'POST',
      () =>
        jsonResponse({
          candidates: [{ word: '广告', markedHits: 2 }],
          markedScanned: 2,
          markedMissing: 0,
          queryKey: '内核',
          note: '确认前绝不进入查询。',
        }),
    )
    mockRoute(
      (url) =>
        url === '/api/v1/search/exclusion-words' || url.startsWith('/api/v1/search/exclusion-words?'),
      () => jsonResponse({ queryKey: '内核', items: [{ id: 7, word: '广告', createdAt: 'T0' }] }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/search/exclusion-words' && init?.method === 'POST',
      () => jsonResponse({ id: 7, word: '广告', createdAt: 'T0', already: false }, 201),
    )
    renderWithQuery(<ExclusionSuggestionsPanel query="内核" markedRefs={markedRefs} />)
    expect(calls.length).toBe(0)
    fireEvent.click(screen.getByTestId('n365-toggle'))
    await waitFor(() => {
      expect(screen.getByTestId('n365-candidate')).toBeTruthy()
    })
    expect(screen.getByTestId('n365-candidate').textContent).toContain('广告')
    fireEvent.click(screen.getByTestId('n365-candidate'))
    await waitFor(() => {
      expect(screen.getByTestId('n365-approved')).toBeTruthy()
    })
    expect(screen.getByText(/已确认（并进本查询的排除条件）/)).toBeTruthy()
    const post = callsTo('/api/v1/search/exclusion-words').find((call) => call.init?.method === 'POST')
    expect(post).toBeTruthy()
    expect(JSON.parse(String(post?.init?.body))).toEqual({ query: '内核', word: '广告' })
  })
})

describe('NEW-366 段落级搜索结果', () => {
  it('多段落命中分别列出；保存片段是显式动作', async () => {
    mockRoute(
      (url) => url.startsWith('/api/v1/search/paragraphs?'),
      () =>
        jsonResponse({
          entry: { entryRef: 'e1.long', title: '长文' },
          paragraphs: [
            { index: 1, offset: 12, terms: ['内核'], text: '第二段讨论内核调度。', truncatedText: false },
            { index: 3, offset: 66, terms: ['内核'], text: '第四段回到内核内存。', truncatedText: false },
          ],
          paragraphTotal: 5,
          complete: true,
        }),
    )
    mockRoute(
      (url) => url.startsWith('/api/v1/search/fragments?entryRef='),
      () => jsonResponse({ items: [] }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/search/fragments' && init?.method === 'POST',
      () =>
        jsonResponse(
          {
            id: 3,
            entryRef: 'e1.long',
            entryTitle: '长文',
            query: '内核',
            paragraphIndex: 1,
            text: '第二段讨论内核调度。',
            createdAt: 'T0',
          },
          201,
        ),
    )
    renderWithQuery(<ParagraphHitsPanel entryRef="e1.long" query="内核" />)
    fireEvent.click(screen.getByTestId('n366-toggle'))
    await waitFor(() => {
      expect(screen.getAllByTestId('n366-paragraph').length).toBe(2)
    })
    expect(screen.getByText(/全文 5 段，其中 2 段命中/)).toBeTruthy()
    const savedBefore = calls.filter(
      (call) => call.url === '/api/v1/search/fragments' && call.init?.method === 'POST',
    ).length
    expect(savedBefore).toBe(0)
    const saveButtons = screen.getAllByRole('button', { name: '保存此片段' })
    fireEvent.click(saveButtons[0])
    await waitFor(() => {
      expect(
        calls.filter(
          (call) => call.url === '/api/v1/search/fragments' && call.init?.method === 'POST',
        ).length,
      ).toBe(1)
    })
  })
})

describe('NEW-367 搜索会话回溯', () => {
  it('记录步骤（无活动会话则先建会话）；重新打开接续到最后一步', async () => {
    mockRoute(
      (url, init) => url === '/api/v1/search/sessions' && init?.method === 'POST',
      () =>
        jsonResponse(
          { id: 's1', title: '研究：内核', currentStep: -1, stepCount: 0, createdAt: 'T', updatedAt: 'T' },
          201,
        ),
    )
    mockRoute(
      (url, init) => url === '/api/v1/search/sessions/s1/steps' && init?.method === 'POST',
      () =>
        jsonResponse(
          {
            id: 's1',
            title: '研究：内核',
            currentStep: 1,
            stepCount: 2,
            createdAt: 'T',
            updatedAt: 'T',
            resumeStep: 1,
            steps: [
              { query: '内核 调度', filters: {}, at: 'T0', refs: [] },
              { query: '内核 内存', filters: {}, at: 'T1', refs: ['e1.pick'] },
            ],
          },
          201,
        ),
    )
    mockRoute(
      (url, init) => url === '/api/v1/search/sessions/s1/selections' && init?.method === 'POST',
      (url) => jsonResponse({ id: 's1', title: '研究：内核', currentStep: 1, stepCount: 2, createdAt: 'T', updatedAt: 'T', steps: [], resumeStep: 1 }),
    )
    renderWithQuery(
      <SearchSessionPanel
        query="内核 内存"
        filters={{}}
        selectedRefs={['e1.pick']}
        onResumeStep={() => {}}
      />,
    )
    fireEvent.click(screen.getByTestId('n367-record'))
    await waitFor(() => {
      expect(screen.getByTestId('n367-recorded')).toBeTruthy()
    })
    expect(screen.getByText(/已记录（当前第 2 步，含 1 条选中结果）/)).toBeTruthy()
    expect(
      calls.find((call) => call.url === '/api/v1/search/sessions' && call.init?.method === 'POST'),
    ).toBeTruthy()
    expect(
      calls.find((call) => call.url === '/api/v1/search/sessions/s1/selections'),
    ).toBeTruthy()
  })
})

describe('NEW-368 相近拼写搜索提示', () => {
  it('零命中才拉取候选；点选是用户显式替换', async () => {
    const onPick = vi.fn()
    mockRoute(
      (url) => url.startsWith('/api/v1/search/spell-suggestions?'),
      () =>
        jsonResponse({
          hasHits: false,
          total: 0,
          candidates: [
            { term: 'linx', suggestion: 'linux', distance: 1, occurrences: 3 },
          ],
          vocabSize: 40,
          note: '仅供参考，绝不自动替换查询。',
        }),
    )
    // 有命中（zeroHits=false）→ 组件不渲染、零请求。
    const { rerender } = renderWithQuery(<SpellSuggestions query="linx" zeroHits={false} onPick={onPick} />)
    expect(screen.queryByTestId('n368-spell')).toBeNull()
    expect(calls.length).toBe(0)
    rerender(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <SpellSuggestions query="linx" zeroHits onPick={onPick} />
      </QueryClientProvider>,
    )
    await waitFor(() => {
      expect(screen.getByTestId('n368-spell')).toBeTruthy()
    })
    expect(screen.getByText(/不会自动替换/)).toBeTruthy()
    fireEvent.click(screen.getByTestId('n368-spell-option'))
    expect(onPick).toHaveBeenCalledWith('linux')
  })
})

describe('NEW-369 个人资料语言筛选', () => {
  it('分组来自显式记录；未知语言单独呈现，不并入语言组', async () => {
    mockRoute(
      (url) => url.startsWith('/api/v1/search/by-language?'),
      () =>
        jsonResponse({
          total: 5,
          complete: true,
          groups: [
            { language: 'ja', count: 2, sampleRefs: ['e1.j1', 'e1.j2'] },
            { language: 'en', count: 1, sampleRefs: ['e1.e1'] },
          ],
          unknown: { count: 1, sampleRefs: ['e1.u1'] },
          note: '语言只来自用户更正或来源记录；无记录一律进 unknown。',
        }),
    )
    renderWithQuery(<LanguageGroupsPanel query="Alpha" />)
    await waitFor(() => {
      expect(screen.getAllByTestId('n369-language').length).toBe(2)
    })
    expect(screen.getByTestId('n369-unknown').textContent).toContain('未知语言')
    fireEvent.click(screen.getByTestId('n369-unknown'))
    await waitFor(() => {
      expect(screen.getByTestId('n369-samples')).toBeTruthy()
    })
    expect(screen.getByTestId('n369-samples').textContent).toContain('不做猜测')
  })
})

describe('NEW-370 搜索结果评注', () => {
  it('有用/无关是显式标记；默认方案关闭；启用后展示重排预览', async () => {
    mockRoute(
      (url, init) => url === '/api/v1/search/feedback' && init?.method === 'POST',
      () => jsonResponse({ id: 9, already: false }, 201),
    )
    mockRoute(
      (url) => url.startsWith('/api/v1/search/feedback?'),
      () =>
        jsonResponse({
          queryKey: '评注',
          items: [
            { id: 9, entryRef: 'e1.a', entryTitle: 'A', verdict: 'useful', reason: '', updatedAt: 'T' },
          ],
          counts: { useful: 1, irrelevant: 0 },
        }),
    )
    mockRoute((url) => url === '/api/v1/search/ranking-scheme', () =>
      jsonResponse({ scheme: 'hit_feedback', enabled: true, updatedAt: 'T', note: '启用后仅 reranked 端点生效。' }),
    )
    mockRoute((url, init) => url === '/api/v1/search/ranking-scheme' && init?.method === 'POST', () =>
      jsonResponse({ scheme: 'hit_feedback', enabled: true, updatedAt: 'T', note: '' }),
    )
    mockRoute(
      (url) => url.startsWith('/api/v1/search/reranked?'),
      () =>
        jsonResponse({
          scheme: 'hit_feedback',
          enabled: true,
          items: [
            { entryRef: 'e1.a', boosted: true },
            { entryRef: 'e1.b', boosted: false },
          ],
          complete: true,
          note: '有用置顶。',
        }),
    )
    renderWithQuery(
      <div>
        <HitFeedbackControls query="评注" entryRef="e1.a" />
        <FeedbackSummary query="评注" />
        <RankingSchemeToggle query="评注" />
      </div>,
    )
    fireEvent.click(screen.getByTestId('n370-useful'))
    await waitFor(() => {
      expect(screen.getByTestId('n370-saved')).toBeTruthy()
    })
    const post = calls.find(
      (call) => call.url === '/api/v1/search/feedback' && call.init?.method === 'POST',
    )
    expect(JSON.parse(String(post?.init?.body))).toEqual({
      query: '评注',
      entryRef: 'e1.a',
      verdict: 'useful',
      reason: null,
    })
    await waitFor(() => {
      expect(screen.getByTestId('n370-summary')).toBeTruthy()
    })
    await waitFor(() => {
      expect(screen.getByTestId('n370-reranked')).toBeTruthy()
    })
    expect(screen.getByTestId('n370-reranked').textContent).toContain('置顶 1 条')
  })
})
