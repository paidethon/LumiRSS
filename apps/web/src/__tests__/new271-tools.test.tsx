/** NEW-271..280 Web 入口测试 — AI 任务控制台的渲染与交互主路径。
 *
 * 环境：jsdom；fetch 按 URL 匹配 mock（服务真源在 BFF，后端口径见
 * tests/test_new27*.py）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { New271AiControlTools } from '../components/new271/New271AiControlTools'

const ENTRY_REF = 'e1.abc'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderWithQuery(ui: React.ReactElement): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

const fetchCalls: { url: string; init?: RequestInit }[] = []
let routes: {
  match: (url: string, init?: RequestInit) => boolean
  respond: (url: string, init?: RequestInit) => Response
}[] = []

function mockRoute(
  matcher: (url: string, init?: RequestInit) => boolean,
  responder: (url: string, init?: RequestInit) => Response,
): void {
  routes.push({ match: matcher, respond: responder })
}

function lastCall(url: string): RequestInit {
  const call = fetchCalls.filter((c) => c.url === url).at(-1)
  expect(call, `expected a fetch call to ${url}`).toBeDefined()
  return call.init ?? {}
}

/** 展开控制台组合 + 指定子工具（两级情境展开）。 */
function expand(subsectionId: string): void {
  fireEvent.click(screen.getByRole('button', { name: /AI 任务控制台（/ }))
  const toggles = screen.getAllByRole('button').filter((button) => {
    const host = button.closest('[data-new271-subsection]')
    return host !== null && host.getAttribute('data-new271-subsection') === subsectionId
  })
  expect(toggles.length).toBeGreaterThan(0)
  fireEvent.click(toggles[0])
}

beforeEach(() => {
  fetchCalls.length = 0
  routes = []
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    fetchCalls.push({ url, init })
    for (const route of routes) {
      if (route.match(url, init)) return route.respond(url, init)
    }
    return jsonResponse({ error: { type: 'unmocked', message: url } }, 404)
  }) as typeof fetch
})

afterEach(() => {
  cleanup()
  routes = []
})

describe('NEW-271..280 AI 任务控制台（New271AiControlTools）', () => {
  it('折叠态零请求；aria-expanded 随开关翻转（两级情境展开）', () => {
    renderWithQuery(<New271AiControlTools entryRef={ENTRY_REF} />)
    const toggle = screen.getByRole('button', { name: /AI 任务控制台（/ })
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(fetchCalls).toHaveLength(0)
    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    // 组合展开只挂载折叠的子工具：仍然零请求
    expect(fetchCalls).toHaveLength(0)
    expect(screen.getByText('NEW-271 输入预览（执行前看将发送的范围）')).toBeTruthy()
  })

  it('NEW-271 输入预览：分段表如实渲染 + 诚实说明；请求体带笔记', async () => {
    mockRoute(
      (url) => url === `/api/v1/entries/${ENTRY_REF}/ai-input-preview`,
      () =>
        jsonResponse({
          purpose: 'conversation',
          title: '一篇文章',
          feedTitle: '某来源',
          sections: [
            { key: 'body', label: '文章正文', included: true, totalChars: 800, effectiveChars: 800 },
            { key: 'userNote', label: '用户笔记', included: true, totalChars: 12, effectiveChars: 12 },
            { key: 'history', label: '对话历史', included: false, totalChars: 0, effectiveChars: 0 },
            { key: 'question', label: '本次问题', included: true, totalChars: 9, effectiveChars: 9 },
          ],
          effectiveText: '正文…',
          note: '我的笔记',
          noteChars: 12,
          truncated: false,
          totalEffectiveChars: 821,
          honestyNote: '预览与真实发送共用同一组装。',
        }),
    )
    renderWithQuery(<New271AiControlTools entryRef={ENTRY_REF} />)
    expand('input-preview')
    fireEvent.change(screen.getByLabelText('随问发送的用户笔记（可选，≤2000 字符）'), {
      target: { value: '我的笔记' },
    })
    fireEvent.click(screen.getByText('预览将发送的输入'))
    await waitFor(() => expect(screen.getByText('预览与真实发送共用同一组装。')).toBeTruthy())
    expect(screen.getByText('有效输入共 821 字符')).toBeTruthy()
    const bodyRow = screen.getByText('文章正文').closest('tr')
    expect(bodyRow?.textContent).toContain('800')
    expect(JSON.parse(String(lastCall(`/api/v1/entries/${ENTRY_REF}/ai-input-preview`).body))).toMatchObject({
      purpose: 'conversation',
      note: '我的笔记',
    })
  })

  it('NEW-272 草稿对照：生成入库、diff 行数与 unified、组内单选保留', async () => {
    const draftA = {
      id: 'd-a', entryRef: ENTRY_REF, materialHash: 'm1', schemeLabel: '方案A',
      promptText: '', draftText: '草稿一', sourceKind: 'generated', kept: false, createdAt: 't',
    }
    const draftB = { ...draftA, id: 'd-b', schemeLabel: '方案B', draftText: '草稿二' }
    mockRoute(
      (url, init) => url === `/api/v1/entries/${ENTRY_REF}/ai-drafts` && (!init?.method || init.method === 'GET'),
      () => jsonResponse({ entryRef: ENTRY_REF, groups: [{ materialHash: 'm1', drafts: [draftA, draftB] }], total: 2 }),
    )
    mockRoute(
      (url) => url === `/api/v1/entries/${ENTRY_REF}/ai-drafts/generate`,
      () => jsonResponse(draftA, 201),
    )
    mockRoute(
      (url) => url === `/api/v1/ai-drafts/d-a/diff/d-b`,
      () => jsonResponse({ a: draftA, b: draftB, unified: '--- a\n+++ b\n-草稿一\n+草稿二', addedLines: 1, removedLines: 1, identical: false }),
    )
    mockRoute(
      (url) => url === '/api/v1/ai-drafts/d-a/keep',
      () => jsonResponse({ ...draftA, kept: true }),
    )
    renderWithQuery(<New271AiControlTools entryRef={ENTRY_REF} />)
    expand('ai-drafts')
    await waitFor(() => expect(screen.getByText(/方案A/)).toBeTruthy())
    fireEvent.change(screen.getByLabelText('提示方案名称'), { target: { value: '方案C' } })
    fireEvent.click(screen.getByText('按此方案生成草稿'))
    await waitFor(() =>
      expect(lastCall(`/api/v1/entries/${ENTRY_REF}/ai-drafts/generate`).method).toBe('POST'),
    )
    fireEvent.click(screen.getByLabelText('选中草稿 方案A 参与对照'))
    fireEvent.click(screen.getByLabelText('选中草稿 方案B 参与对照'))
    fireEvent.click(screen.getByText('对照选中的两份草稿'))
    await waitFor(() => expect(screen.getByText(/差异：新增 1 行 \/ 删除 1 行/)).toBeTruthy())
    fireEvent.click(screen.getAllByText('保留此稿')[0] as HTMLButtonElement)
    await waitFor(() => expect(lastCall('/api/v1/ai-drafts/d-a/keep').method).toBe('POST'))
  })

  it('NEW-273 模板试运行：逐样本结果 + 实际用量 + 显式启用', async () => {
    const trial = {
      id: 'tr-1', templateText: '总结：{text}', sampleKind: 'custom',
      results: [{ title: '样本一', inputChars: 40, output: '输出一', status: 'success' }],
      promotedTemplateId: null, createdAt: 't',
    }
    mockRoute(
      (url, init) => url === '/api/v1/ai/template-trials' && (!init?.method || init.method === 'GET'),
      () => jsonResponse({ items: [trial], total: 1 }),
    )
    mockRoute(
      (url) => url === '/api/v1/ai/template-trials',
      () => jsonResponse(trial, 201),
    )
    mockRoute(
      (url) => url === '/api/v1/ai/template-trials/tr-1/promote',
      () => jsonResponse({ ...trial, promotedTemplateId: 'qt-9' }),
    )
    renderWithQuery(<New271AiControlTools entryRef={ENTRY_REF} />)
    expand('template-trials')
    await waitFor(() => expect(screen.getByText(/实际调用 1 次/)).toBeTruthy())
    fireEvent.change(screen.getByLabelText('模板提示词'), { target: { value: '总结：{text}' } })
    fireEvent.change(screen.getByLabelText('样本正文（合成或本人选定）'), { target: { value: '一些文本' } })
    fireEvent.click(screen.getByText('试跑模板'))
    await waitFor(() =>
      expect(lastCall('/api/v1/ai/template-trials').method).toBe('POST'),
    )
    fireEvent.change(screen.getByLabelText('启用为正式模板的名称'), { target: { value: '我的模板' } })
    fireEvent.click(screen.getByText('启用'))
    await waitFor(() =>
      expect(lastCall('/api/v1/ai/template-trials/tr-1/promote').method).toBe('POST'),
    )
  })

  it('NEW-274 引用核验：未定位如实标出；确认勾选前不可标已核对', async () => {
    const check = {
      id: 'ck-1', answerText: '回答', citations: [
        { index: 1, entryRef: 'e1.abc', claim: '原句', status: 'found', excerpt: '原句', offset: 0 },
        { index: 2, entryRef: 'e2.abc', claim: '改写句', status: 'not_found' },
      ],
      checked: false, confirmedMissing: false, missingCount: 1, createdAt: 't', checkedAt: null,
      honestyNote: '定位是字面子串匹配。',
    }
    mockRoute(
      (url) => url === '/api/v1/ai/citation-checks',
      () => jsonResponse(check, 201),
    )
    mockRoute(
      (url) => url === '/api/v1/ai/citation-checks/ck-1/mark-checked',
      () => jsonResponse({ ...check, checked: true, confirmedMissing: true }),
    )
    renderWithQuery(<New271AiControlTools entryRef={ENTRY_REF} />)
    expand('citation-checks')
    fireEvent.change(screen.getByLabelText('待核验的回答文本'), { target: { value: '回答' } })
    fireEvent.click(screen.getByText('逐条定位引用'))
    await waitFor(() => expect(screen.getByText(/原文中找不到/)).toBeTruthy())
    const markButton = screen.getByText('标为已核对').closest('button') as HTMLButtonElement
    expect(markButton.disabled).toBe(true) // 存在未定位 → 未勾选确认前禁止
    fireEvent.click(screen.getByLabelText('我知道有 1 条引用未定位，仍确认标为已核对'))
    expect((screen.getByText('标为已核对').closest('button') as HTMLButtonElement).disabled).toBe(false)
    fireEvent.click(screen.getByText('标为已核对'))
    await waitFor(() =>
      expect(lastCall('/api/v1/ai/citation-checks/ck-1/mark-checked').method).toBe('POST'),
    )
  })

  it('NEW-275 批量审批单：创建带清单与预算 → 批准 → 执行', async () => {
    // 状态机随动作推进：draft → approved → completed（预算用尽项如实标注）
    let status: 'draft' | 'approved' | 'completed' = 'draft'
    const approval = () => ({
      id: 'ba-1', kind: 'summary', budgetCalls: 2, usedCalls: status === 'draft' ? 0 : 1, status,
      createdAt: 't', approvedAt: status === 'draft' ? null : 't', closedAt: null,
      items: [
        { id: 'i-1', entryRef: ENTRY_REF, status: status === 'draft' ? 'pending' : 'done', errorType: null, finishedAt: status === 'draft' ? null : 't', ord: 0 },
        { id: 'i-2', entryRef: 'e2.abc', status: status === 'draft' ? 'pending' : 'over_budget', errorType: null, finishedAt: status === 'draft' ? null : 't', ord: 1 },
      ],
    })
    mockRoute(
      (url, init) => url === '/api/v1/ai/batch-approvals' && (!init?.method || init.method === 'GET'),
      () => jsonResponse({ items: [approval()], total: 1 }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/ai/batch-approvals' && init?.method === 'POST',
      () => jsonResponse(approval(), 201),
    )
    mockRoute(
      (url) => url === '/api/v1/ai/batch-approvals/ba-1/approve',
      () => {
        status = 'approved'
        return jsonResponse(approval())
      },
    )
    mockRoute(
      (url) => url === '/api/v1/ai/batch-approvals/ba-1/execute',
      () => {
        status = 'completed'
        return jsonResponse(approval())
      },
    )
    renderWithQuery(<New271AiControlTools entryRef={ENTRY_REF} />)
    expand('batch-approvals')
    await waitFor(() => expect(screen.getByText(/预算 2 次调用/)).toBeTruthy())
    fireEvent.change(screen.getByLabelText('本次预算（最多 AI 调用数，1–20）'), { target: { value: '2' } })
    fireEvent.click(screen.getByText('生成审批单（任务类型：摘要）'))
    await waitFor(() => {
      const body = JSON.parse(String(lastCall('/api/v1/ai/batch-approvals').body))
      expect(body).toMatchObject({ kind: 'summary', budgetCalls: 2, entryRefs: [ENTRY_REF] })
    })
    fireEvent.click(screen.getByText('批准'))
    await waitFor(() => expect(lastCall('/api/v1/ai/batch-approvals/ba-1/approve').method).toBe('POST'))
    fireEvent.click(screen.getByText('执行'))
    await waitFor(() => expect(lastCall('/api/v1/ai/batch-approvals/ba-1/execute').method).toBe('POST'))
    await waitFor(() => expect(screen.getByText(/预算用尽（未执行）/)).toBeTruthy())
  })

  it('NEW-276 失败重放：脱敏诊断展示；conversation 的 same 被禁用、modified 需新问题', async () => {
    const diagnostic = {
      id: 'tk-1', kind: 'conversation', status: 'failed', model: 'model-a', entryRef: ENTRY_REF,
      inputChars: 300, durationMs: 1200, errorType: 'AiTimeout', createdAt: 't',
      requestShape: {
        endpoint: '/api/v1/entries/{entryRef}/conversation/messages',
        boundedFields: ['question(≤4000 chars)', 'maxChars(512–50000)'],
        note: '问题正文不入库（失败不持久化），无法原样重放。',
      },
      redactionNote: '诊断只含结构字段。',
      replayModes: ['modified'],
    }
    mockRoute(
      (url) => url === '/api/v1/ai/tasks/tk-1/replay-diagnostic',
      () => jsonResponse(diagnostic),
    )
    mockRoute(
      (url) => url === '/api/v1/ai/tasks/tk-1/replay',
      () => jsonResponse({ replayId: 'r-1', originalTaskId: 'tk-1', replayTaskId: 'tk-2', mode: 'modified' }, 201),
    )
    renderWithQuery(<New271AiControlTools entryRef={ENTRY_REF} />)
    expand('task-replays')
    fireEvent.change(screen.getByLabelText('失败任务 ID'), { target: { value: 'tk-1' } })
    fireEvent.click(screen.getByText('查看脱敏诊断'))
    await waitFor(() => expect(screen.getByText(/失败：AiTimeout/)).toBeTruthy())
    expect(screen.getByText(/诊断只含结构字段/)).toBeTruthy()
    expect((screen.getByLabelText('相同配置重试') as HTMLInputElement).disabled).toBe(true)
    fireEvent.click(screen.getByLabelText('修改后新建'))
    const retry = screen.getByText('重试').closest('button') as HTMLButtonElement
    expect(retry.disabled).toBe(true) // 新问题未填
    fireEvent.change(screen.getByLabelText('新问题（原问题未入库，无法重用）'), { target: { value: '换个问法' } })
    fireEvent.click(retry)
    await waitFor(() => {
      expect(lastCall('/api/v1/ai/tasks/tk-1/replay').method).toBe('POST')
      expect(JSON.parse(String(lastCall('/api/v1/ai/tasks/tk-1/replay').body))).toMatchObject({
        mode: 'modified', question: '换个问法',
      })
    })
    await waitFor(() => expect(screen.getByText(/新任务 tk-2/)).toBeTruthy())
  })

  it('NEW-277 用途约束：保存 PUT allowedPurposes；purpose-options 给出被阻断提示', async () => {
    mockRoute(
      (url) => url.endsWith('/purpose-constraints') && url.includes('prof-1'),
      (url, init) => {
        if (init?.method === 'PUT') return jsonResponse({ profileId: 'prof-1', profileLabel: '本地模型', allowedPurposes: ['summary'], purposes: ['summary', 'chat'] })
        return jsonResponse({ error: { type: 'constraint_not_found', message: '无' } }, 404)
      },
    )
    mockRoute(
      (url) => url.startsWith('/api/v1/ai/purpose-options'),
      () =>
        jsonResponse({
          purpose: 'chat', purposes: ['summary', 'chat'], mappedProfileId: 'prof-1', blocked: true,
          options: [
            { profileId: 'prof-1', profileLabel: '本地模型', eligible: false, isCurrentMapping: true },
            { profileId: 'prof-2', profileLabel: '云端模型', eligible: true, isCurrentMapping: false },
          ],
          honestyNote: '约束只对显式映射档生效。',
        }),
    )
    renderWithQuery(<New271AiControlTools entryRef={ENTRY_REF} />)
    expand('purpose-constraints')
    fireEvent.change(screen.getByLabelText('配置档 ID'), { target: { value: 'prof-1' } })
    fireEvent.click(screen.getByText('读取'))
    await waitFor(() => expect(screen.getByLabelText('摘要')).toBeTruthy())
    fireEvent.click(screen.getByLabelText('摘要'))
    fireEvent.click(screen.getByText('保存约束'))
    await waitFor(() => {
      expect(lastCall('/api/v1/settings/ai/profiles/prof-1/purpose-constraints').method).toBe('PUT')
      expect(JSON.parse(String(lastCall('/api/v1/settings/ai/profiles/prof-1/purpose-constraints').body)))
        .toMatchObject({ allowedPurposes: ['summary'] })
    })
    fireEvent.change(screen.getByLabelText('查询某用途当前可选的模型'), { target: { value: 'chat' } })
    fireEvent.click(screen.getByText('查询'))
    await waitFor(() => expect(screen.getByText(/当前映射模型被约束阻断/)).toBeTruthy())
    expect(screen.getByText(/云端模型$/)).toBeTruthy()
  })

  it('NEW-278 隐私过滤：显式勾选字段保存 + 过滤差异预览 + 诚实口径', async () => {
    const view = {
      exclude: [], fields: ['feedTitle', 'cachedSummary', 'userNote'],
      fieldLabels: { feedTitle: '文章来源', cachedSummary: 'AI 摘要（缓存）', userNote: '用户笔记' },
      honestyNote: '过滤是显式字段勾选，不是自动识别所有秘密。',
    }
    mockRoute(
      (url, init) => url === '/api/v1/ai/privacy-filters' && (!init?.method || init.method === 'GET'),
      () => jsonResponse(view),
    )
    mockRoute(
      (url, init) => url === '/api/v1/ai/privacy-filters' && init?.method === 'PUT',
      () => jsonResponse({ ...view, exclude: ['feedTitle'] }),
    )
    mockRoute(
      (url) => url === '/api/v1/ai/privacy-filters/diff',
      () =>
        jsonResponse({
          sections: [
            { key: 'feedTitle', label: '文章来源', included: false, totalChars: 4, effectiveChars: 0, excludedByFilter: true },
            { key: 'body', label: '文章正文', included: true, totalChars: 800, effectiveChars: 800 },
          ],
          removedChars: 4, exclude: ['feedTitle'], honestyNote: view.honestyNote,
        }),
    )
    renderWithQuery(<New271AiControlTools entryRef={ENTRY_REF} />)
    expand('privacy-filters')
    await waitFor(() => expect(screen.getByLabelText('文章来源')).toBeTruthy())
    fireEvent.click(screen.getByLabelText('文章来源'))
    fireEvent.click(screen.getByText('保存过滤选择'))
    await waitFor(() => {
      expect(lastCall('/api/v1/ai/privacy-filters').method).toBe('PUT')
      expect(JSON.parse(String(lastCall('/api/v1/ai/privacy-filters').body))).toMatchObject({ exclude: ['feedTitle'] })
    })
    fireEvent.click(screen.getByText('预览这篇文章的过滤差异'))
    await waitFor(() => expect(screen.getByText(/被过滤掉 4 字符/)).toBeTruthy())
    expect(screen.getByText(/文章来源：不发送/)).toBeTruthy()
    expect(screen.getByText(/不是自动识别所有秘密/)).toBeTruthy()
  })

  it('NEW-279 结论采纳：写入新笔记带 AI 标记；改写冲突 409 展示现状不覆盖', async () => {
    const adoption = {
      id: 'ad-1', entryRef: null, conclusion: '结论甲', citations: [{ index: 1, entryRef: 'e1.abc' }],
      model: 'conversation', noteUuid: 'n-1', noteUpdatedAt: 't', noteContentHash: 'h',
      createdAt: 't', updatedAt: 't',
    }
    mockRoute(
      (url, init) => url === '/api/v1/ai/answer-adoptions' && (!init?.method || init.method === 'GET'),
      () => jsonResponse({ items: [adoption], total: 1 }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/ai/answer-adoptions' && init?.method === 'POST',
      () => jsonResponse(adoption, 201),
    )
    mockRoute(
      (url, init) => url === '/api/v1/ai/answer-adoptions/ad-1' && init?.method === 'PATCH',
      () =>
        jsonResponse(
          {
            error: {
              type: 'note_diverged', message: '笔记已被直接修改。',
              noteUuid: 'n-1', noteUpdatedAt: 't2', noteContentMd: '我手动重写的全部内容。',
            },
          },
          409,
        ),
    )
    mockRoute(
      (url, init) => url === '/api/v1/ai/answer-adoptions/ad-1' && init?.method === 'DELETE',
      () => new Response(null, { status: 204 }),
    )
    renderWithQuery(<New271AiControlTools entryRef={ENTRY_REF} />)
    expand('answer-adoptions')
    await waitFor(() => expect(screen.getByText(/结论甲/)).toBeTruthy())
    fireEvent.change(screen.getByLabelText('要采纳的结论（可改写后再采纳）'), { target: { value: '结论乙' } })
    fireEvent.click(screen.getByText('采纳到个人笔记'))
    await waitFor(() => {
      expect(lastCall('/api/v1/ai/answer-adoptions').method).toBe('POST')
      expect(JSON.parse(String(lastCall('/api/v1/ai/answer-adoptions').body))).toMatchObject({
        conclusion: '结论乙', model: 'conversation',
      })
    })
    fireEvent.change(screen.getByLabelText('改写这条结论'), { target: { value: '迟到的改写' } })
    fireEvent.click(screen.getByText('改写'))
    await waitFor(() => expect(screen.getByText(/笔记已被直接修改；改写未应用/)).toBeTruthy())
    expect(screen.getByText('我手动重写的全部内容。')).toBeTruthy()
    fireEvent.click(screen.getByText('删除记录'))
    await waitFor(() => expect(lastCall('/api/v1/ai/answer-adoptions/ad-1').method).toBe('DELETE'))
  })

  it('NEW-280 配额分桶：快照显示用量与接近限额告警；设置分桶 PUT', async () => {
    const snapshot = {
      window: 'day', windowKey: '2026-09-29', windowReset: 't',
      buckets: [
        { purpose: 'summary', maxCalls: 10, used: 9, remaining: 1, nearLimit: true, updatedAt: 't' },
      ],
      purposes: ['summary', 'chat'],
      honestyNote: '分桶先于全局配额；超额会明确拒绝。',
    }
    mockRoute(
      (url, init) => url === '/api/v1/ai/quota/buckets' && (!init?.method || init.method === 'GET'),
      () => jsonResponse(snapshot),
    )
    mockRoute(
      (url, init) => url === '/api/v1/ai/quota/buckets/chat' && init?.method === 'PUT',
      () => jsonResponse({ purpose: 'chat', maxCalls: 5 }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/ai/quota/buckets/summary' && init?.method === 'DELETE',
      () => new Response(null, { status: 204 }),
    )
    renderWithQuery(<New271AiControlTools entryRef={ENTRY_REF} />)
    expand('quota-buckets')
    await waitFor(() => expect(screen.getByText(/摘要：已用 9 \/ 上限 10/)).toBeTruthy())
    expect(screen.getByText(/已接近限额，请调整分桶/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText('用途'), { target: { value: 'chat' } })
    fireEvent.change(screen.getByLabelText('本窗口上限（次）'), { target: { value: '5' } })
    fireEvent.click(screen.getByText('设置分桶'))
    await waitFor(() => {
      expect(lastCall('/api/v1/ai/quota/buckets/chat').method).toBe('PUT')
      expect(JSON.parse(String(lastCall('/api/v1/ai/quota/buckets/chat').body))).toMatchObject({ maxCalls: 5 })
    })
    fireEvent.click(screen.getByText('移除此分桶'))
    await waitFor(() => expect(lastCall('/api/v1/ai/quota/buckets/summary').method).toBe('DELETE'))
  })
})
