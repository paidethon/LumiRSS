/** N030 测试 — 路由可复用参数方案（F047 对话框 保存为方案 / 我的方案 /
 * 回填）。覆盖：保存为方案（请求体带路由 + 当前参数组合）、方案列表
 * 渲染（敏感值只以 '***' 哨兵出现）、应用回填（非敏感直接回填、敏感
 * 键必须重新输入后才能预览）、删除。fetch 全部 mock。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RsshubRouteParamsDialog } from '../components/rsshub-route-params-dialog'
import type { Subscription } from '../api/types'

const ROUTES = {
  configured: true,
  routes: [
    {
      id: 'github-starred-repos',
      title: 'GitHub 用户星标仓库',
      description: '某位 GitHub 用户 star 过的仓库动态。',
      pathTemplate: '/github/starred_repos/{user}',
      parameters: [
        {
          key: 'user',
          label: 'GitHub 用户名',
          required: true,
          pattern: '^[a-zA-Z0-9-]{1,39}$',
          example: 'DIYgod',
          help: 'GitHub 用户名（字母 / 数字 / 连字符）。',
        },
      ],
    },
  ],
}

const PRESETS = [
  {
    id: 'p1',
    routeKey: 'github-starred-repos|lang=en',
    templateId: 'github-starred-repos',
    name: '英文界面',
    params: { user: 'DIYgod', lang: 'en' },
    hasSensitive: false,
    createdAt: '2026-09-24T10:00:00+00:00',
  },
  {
    id: 'p2',
    routeKey: 'github-starred-repos|accessKey=***',
    templateId: 'github-starred-repos',
    name: '带密钥',
    params: { user: 'DIYgod', accessKey: '***' },
    hasSensitive: true,
    createdAt: '2026-09-24T09:00:00+00:00',
  },
]

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function makeFetchHandler(map: Record<string, () => Response>) {
  const calls: { method: string; url: string; body?: unknown }[] = []
  const fn = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    let body: unknown
    try {
      body = init?.body !== undefined ? JSON.parse(String(init.body)) : undefined
    } catch {
      body = undefined
    }
    const route = `${method} ${url.split('?')[0]}`
    const handler = map[route]
    if (handler === undefined) {
      throw new Error(`unexpected fetch: ${route}`)
    }
    calls.push({ method, url, body })
    return handler()
  })
  return { fn, calls }
}

const SUBSCRIPTION: Subscription = {
  subscriptionRef: 's1.ZmVlZC85',
  title: 'DIYgod 的星标仓库',
  feedUrl: 'http://rsshub:1200/github/starred_repos/DIYgod',
  category: null,
}

function renderDialog(map: Record<string, () => Response>) {
  const fetchState = makeFetchHandler(map)
  vi.stubGlobal('fetch', fetchState.fn)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <RsshubRouteParamsDialog open onClose={() => {}} subscription={SUBSCRIPTION} />
    </QueryClientProvider>,
  )
  return fetchState
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F047 — N030 我的方案', () => {
  it('保存为方案：POST 请求体 = 路由 id + 模板参数反解 + 当前 query', async () => {
    const fetchState = renderDialog({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
      'GET /api/v1/rsshub/param-presets': () => jsonResponse([]),
      'POST /api/v1/rsshub/param-presets': () =>
        jsonResponse(
          {
            id: 'p9',
            routeKey: 'github-starred-repos',
            templateId: 'github-starred-repos',
            name: '默认',
            params: {},
            hasSensitive: false,
            createdAt: '2026-09-25T10:00:00+00:00',
          },
          201,
        ),
    })
    expect(await screen.findByRole('region', { name: '我的方案' })).toBeInTheDocument()
    expect(await screen.findByText('该路由暂无保存的方案。')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('方案名称'), { target: { value: '默认' } })
    fireEvent.click(screen.getByRole('button', { name: /保存为方案/ }))
    await waitFor(() =>
      expect(screen.getByText(/已保存方案「默认」/)).toBeInTheDocument(),
    )
    const createCall = fetchState.calls.find(
      (call) => call.method === 'POST' && call.url === '/api/v1/rsshub/param-presets',
    )
    expect(createCall?.body).toEqual({
      routeId: 'github-starred-repos',
      params: { user: 'DIYgod' },
      name: '默认',
    })
  })

  it('应用方案（无敏感参数）：非敏感参数直接回填新地址', async () => {
    renderDialog({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
      'GET /api/v1/rsshub/param-presets': () => jsonResponse(PRESETS),
      'POST /api/v1/rsshub/param-presets/p1/apply': () =>
        jsonResponse({
          id: 'p1',
          routeKey: 'github-starred-repos|lang=en',
          templateId: 'github-starred-repos',
          params: { user: 'DIYgod', lang: 'en' },
          hasSensitive: false,
          requiresRebind: false,
          sensitiveKeys: [],
        }),
    })
    fireEvent.click(await screen.findByText('英文界面'))
    expect(await screen.findByText(/已回填「英文界面」/)).toBeInTheDocument()
    // 新地址预览带上方案里的 query 参数（路径占位符不重复进 query）
    expect(
      await screen.findByText('http://rsshub:1200/github/starred_repos/DIYgod?lang=en'),
    ).toBeInTheDocument()
  })

  it('应用含敏感参数的方案：哨兵不回填，必须重新输入后才能预览', async () => {
    renderDialog({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
      'GET /api/v1/rsshub/param-presets': () => jsonResponse(PRESETS),
      'POST /api/v1/rsshub/param-presets/p2/apply': () =>
        jsonResponse({
          id: 'p2',
          routeKey: 'github-starred-repos|accessKey=***',
          templateId: 'github-starred-repos',
          params: { user: 'DIYgod', accessKey: '***' },
          hasSensitive: true,
          requiresRebind: true,
          sensitiveKeys: ['accessKey'],
        }),
    })
    fireEvent.click(await screen.findByText('带密钥'))
    // 敏感键进入重新绑定状态（原值 *** 绝不回填）
    expect(await screen.findByText(/敏感参数需重新输入/)).toBeInTheDocument()
    const rebindInput = screen.getByLabelText('重新输入 accessKey')
    expect(rebindInput).toHaveValue('')
    // 未重新输入 → 阻止门 alert 常驻（哨兵永不外发）
    expect(screen.getByRole('alert')).toHaveTextContent(/敏感参数未保存原值/)
    fireEvent.change(rebindInput, { target: { value: 'real-secret' } })
    // 重新输入后阻止门解除
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    // 哨兵原文不出现在任何输入框
    expect(screen.queryByDisplayValue('***')).not.toBeInTheDocument()
  })

  it('方案列表里敏感值只以 *** 哨兵显示', async () => {
    renderDialog({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
      'GET /api/v1/rsshub/param-presets': () => jsonResponse(PRESETS),
    })
    expect(await screen.findByText('带密钥')).toBeInTheDocument()
    expect(screen.getByText(/accessKey=\*\*\*/)).toBeInTheDocument()
  })

  it('删除方案：DELETE 请求到该方案的 id', async () => {
    const fetchState = renderDialog({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
      'GET /api/v1/rsshub/param-presets': () => jsonResponse(PRESETS),
      'DELETE /api/v1/rsshub/param-presets/p1': () => new Response(null, { status: 204 }),
    })
    expect(await screen.findByText('英文界面')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '删除方案 英文界面' }))
    await waitFor(() => {
      expect(
        fetchState.calls.some(
          (call) =>
            call.method === 'DELETE' && call.url === '/api/v1/rsshub/param-presets/p1',
        ),
      ).toBe(true)
    })
  })

  it('方案加载失败：错误 + 重试', async () => {
    let failed = true
    renderDialog({
      'GET /api/v1/rsshub/routes': () => jsonResponse(ROUTES),
      'GET /api/v1/rsshub/param-presets': () =>
        failed
          ? jsonResponse({ error: { type: 'network_error', message: 'x' } }, 500)
          : jsonResponse([]),
    })
    expect(await screen.findByText('方案加载失败。')).toBeInTheDocument()
    failed = false
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByText('该路由暂无保存的方案。')).toBeInTheDocument()
  })
})
