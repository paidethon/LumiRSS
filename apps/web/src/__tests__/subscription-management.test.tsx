/** Gate 3 测试 — 0013 Subscription Center（真实分类 + move/unsubscribe/rename）。
 *
 * 覆盖：真实 category grouping（未分组排最后）、移动到已有分类、
 * 新建分类并移入（newCategoryLabel）、move 409 冲突文案、取消订阅
 * 双重确认 + DELETE + 列表同步 + stale scope 回退、分类重命名 +
 * categoryId 变化后的 scope 回退、未分组无分类菜单、OPML 禁用徽标。
 * fetch 全部 mock，无真实网络。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SubscriptionsPage from '../components/pages/SubscriptionsPage'
import { useReaderUi } from '../store/reader-ui'

const CAT_TECH = { id: 'user/-/label/技术', label: '技术' }
const CAT_DEFAULT = { id: 'user/-/label/未分类', label: '未分类' }
const REF_TECH = 's1.ZmVlZC83'
const REF_LONE = 's1.ZmVlZC84'

const SUBSCRIPTIONS = [
  {
    subscriptionRef: REF_TECH,
    title: 'Tech Feed',
    feedUrl: 'https://tech.example/rss',
    category: CAT_TECH,
  },
  {
    subscriptionRef: REF_LONE,
    title: 'Lone Feed',
    feedUrl: 'https://lone.example/rss',
    category: null,
  },
]

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function empty204(): Response {
  return new Response(null, { status: 204 })
}

/** 可状态化的路由 mock：routes = { 'METHOD url': () => Response }。 */
function makeFetchHandler(routes: Record<string, () => Response>) {
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
    const handler = routes[`${method} ${url}`]
    if (handler === undefined) {
      throw new Error(`unexpected fetch: ${method} ${url}`)
    }
    calls.push({ method, url, body })
    return handler()
  })
  return { fn, calls }
}

function withProviders(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

/** 状态化服务端：subscriptions / categories 可被 mutation 改写。 */
function makeServer() {
  const state = {
    subscriptions: SUBSCRIPTIONS.map((s) => ({ ...s })),
    categories: [CAT_TECH, CAT_DEFAULT].map((c) => ({ ...c })),
  }
  return {
    state,
    routes: {
      'GET /api/v1/subscriptions': () => jsonResponse(state.subscriptions),
      'GET /api/v1/categories': () => jsonResponse(state.categories),
      [`PATCH /api/v1/subscriptions/${REF_TECH}`]: () => empty204(),
      [`PATCH /api/v1/subscriptions/${REF_LONE}`]: () => empty204(),
      [`DELETE /api/v1/subscriptions/${REF_LONE}`]: () => {
        state.subscriptions = state.subscriptions.filter(
          (s) => s.subscriptionRef !== REF_LONE,
        )
        return empty204()
      },
      [`PATCH /api/v1/categories/${encodeURIComponent(CAT_TECH.id)}`]: () => {
        state.categories = state.categories.map((c) =>
          c.id === CAT_TECH.id ? { id: `user/-/label/Tech`, label: 'Tech' } : c,
        )
        state.subscriptions = state.subscriptions.map((s) =>
          s.category?.id === CAT_TECH.id
            ? { ...s, category: { id: 'user/-/label/Tech', label: 'Tech' } }
            : s,
        )
        return empty204()
      },
    },
  }
}

function renderPage(server = makeServer()) {
  const fetchState = makeFetchHandler(server.routes)
  vi.stubGlobal('fetch', fetchState.fn)
  render(withProviders(<SubscriptionsPage />))
  return { fetchState, server }
}

/** 打开某 feed 的 ⋯ 菜单并点一项。 */
async function openFeedMenu(itemName: string, menuLabel: string) {
  fireEvent.click(screen.getByRole('button', { name: menuLabel }))
  fireEvent.click(await screen.findByRole('menuitem', { name: itemName }))
}

beforeEach(() => {
  localStorage.clear()
  useReaderUi.setState({
    section: 'subscriptions',
    view: 'all',
    scope: { kind: 'all' },
    selectedEntryRef: null,
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('真实分类分组', () => {
  it('分类来自 FreshRSS：技术 + 未分组（排最后）；无硬编码分类名', async () => {
    renderPage()
    expect(await screen.findByText('Tech Feed')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^技术/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /未分组/ })).toBeInTheDocument()
    // 计数：技术 1 / 未分组 1
    expect(screen.getByRole('button', { name: /^技术/ }).textContent).toContain('1')
    expect(screen.getByRole('button', { name: /未分组/ }).textContent).toContain('1')
  })

  it('分类折叠：aria-expanded/controls；点击收起隐藏 feeds', async () => {
    renderPage()
    await screen.findByText('Tech Feed')
    const techToggle = screen.getByRole('button', { name: /^技术/ })
    expect(techToggle).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(techToggle)
    expect(screen.queryByText('Tech Feed')).toBeNull()
  })

  it('本地搜索匹配分类名 / 标题；非全局搜索', async () => {
    renderPage()
    await screen.findByText('Tech Feed')
    fireEvent.change(screen.getByRole('searchbox', { name: '搜索订阅源' }), {
      target: { value: '技术' },
    })
    expect(screen.getByText('Tech Feed')).toBeInTheDocument()
    expect(screen.queryByText('Lone Feed')).toBeNull()
  })

  it('未分组没有分类操作菜单（无真实分类实体，禁止伪造 rename）', async () => {
    renderPage()
    await screen.findByText('Lone Feed')
    expect(screen.queryByRole('button', { name: /「未分组」分类操作/ })).toBeNull()
    // 真实分类有菜单
    expect(screen.getByRole('button', { name: '「技术」分类操作' })).toBeInTheDocument()
  })
})

describe('移动到分类', () => {
  it('移动到已有分类：PATCH { categoryId } → invalidate → 列表同步', async () => {
    const { fetchState } = renderPage()
    await screen.findByText('Tech Feed')
    await openFeedMenu('移动到分类', '「Tech Feed」的操作')
    expect(await screen.findByRole('dialog', { name: '移动到分类' })).toBeInTheDocument()
    // 当前分类（技术）被排除；选择默认分类
    fireEvent.change(screen.getByRole('combobox', { name: '目标分类' }), {
      target: { value: CAT_DEFAULT.id },
    })
    fireEvent.click(screen.getByRole('button', { name: '移动' }))
    await waitFor(() => {
      const patch = fetchState.calls.find(
        (c) => c.method === 'PATCH' && c.url.endsWith(REF_TECH),
      )
      expect(patch?.body).toEqual({ categoryId: CAT_DEFAULT.id })
    })
    // dialog 关闭（server-confirmed）
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: '移动到分类' })).toBeNull()
    })
  })

  it('新建分类并移入：PATCH { newCategoryLabel }', async () => {
    const { fetchState } = renderPage()
    await screen.findByText('Tech Feed')
    await openFeedMenu('移动到分类', '「Tech Feed」的操作')
    fireEvent.change(await screen.findByRole('combobox', { name: '目标分类' }), {
      target: { value: '__new_category__' },
    })
    fireEvent.change(screen.getByLabelText('新分类名'), { target: { value: 'AI' } })
    fireEvent.click(screen.getByRole('button', { name: '移动' }))
    await waitFor(() => {
      const patch = fetchState.calls.find(
        (c) => c.method === 'PATCH' && c.url.endsWith(REF_TECH),
      )
      expect(patch?.body).toEqual({ newCategoryLabel: 'AI' })
    })
  })

  it('重名冲突 409：诚实文案，不静默建分类', async () => {
    const server = makeServer()
    server.routes[`PATCH /api/v1/subscriptions/${REF_TECH}`] = () =>
      jsonResponse(
        { error: { type: 'category_label_conflict', message: 'taken' } },
        409,
      )
    renderPage(server)
    await screen.findByText('Tech Feed')
    await openFeedMenu('移动到分类', '「Tech Feed」的操作')
    fireEvent.change(await screen.findByRole('combobox', { name: '目标分类' }), {
      target: { value: '__new_category__' },
    })
    fireEvent.change(screen.getByLabelText('新分类名'), { target: { value: '技术' } })
    fireEvent.click(screen.getByRole('button', { name: '移动' }))
    expect(await screen.findByText('这个名字已被其他分类使用。')).toBeInTheDocument()
    // 失败后 dialog 保留（可修改重试），不误关
    expect(screen.getByRole('dialog', { name: '移动到分类' })).toBeInTheDocument()
  })
})

describe('取消订阅', () => {
  it('双重确认：显示 Feed 名 → 再次确认 → DELETE → 列表同步', async () => {
    const { fetchState } = renderPage()
    await screen.findByText('Lone Feed')
    await openFeedMenu('取消订阅', '「Lone Feed」的操作')
    // 第一层：明确显示 Feed 名
    const dialog = await screen.findByRole('dialog', { name: '取消订阅' })
    expect(dialog).toHaveTextContent('Lone Feed')
    expect(dialog).toHaveTextContent('https://lone.example/rss')
    fireEvent.click(screen.getByRole('button', { name: '取消订阅' }))
    // 第二层：再次确认（危险警示）
    expect(
      await screen.findByRole('dialog', { name: '再次确认' }),
    ).toHaveTextContent('确定要取消订阅吗？')
    fireEvent.click(screen.getByRole('button', { name: '确认取消订阅' }))
    await waitFor(() => {
      const del = fetchState.calls.find((c) => c.method === 'DELETE')
      expect(del?.url).toBe(`/api/v1/subscriptions/${REF_LONE}`)
    })
    // invalidate → refetch → 行消失
    await waitFor(() => {
      expect(screen.queryByText('Lone Feed')).toBeNull()
    })
    expect(screen.getByText('Tech Feed')).toBeInTheDocument()
  })

  it('当前 scope 指向被取消的 feed → 回退「全部」', async () => {
    useReaderUi.setState({
      scope: { kind: 'rss-feed', feedUrl: 'https://lone.example/rss' },
      selectedEntryRef: 'e1.x',
    })
    renderPage()
    await screen.findByText('Lone Feed')
    await openFeedMenu('取消订阅', '「Lone Feed」的操作')
    fireEvent.click(await screen.findByRole('button', { name: '取消订阅' }))
    fireEvent.click(screen.getByRole('button', { name: '确认取消订阅' }))
    await waitFor(() => {
      expect(useReaderUi.getState().scope).toEqual({ kind: 'all' })
    })
    // 选择也被清空（selectScope 语义）
    expect(useReaderUi.getState().selectedEntryRef).toBeNull()
  })

  it('stale feed scope（服务端已无此 feed）在加载后回退', async () => {
    useReaderUi.setState({ scope: { kind: 'rss-feed', feedUrl: 'https://gone.example/rss' } })
    renderPage()
    await screen.findByText('Tech Feed')
    await waitFor(() => {
      expect(useReaderUi.getState().scope).toEqual({ kind: 'all' })
    })
  })
})

describe('重命名分类', () => {
  it('重命名：PATCH categories → invalidate → 新分类名出现', async () => {
    const { fetchState } = renderPage()
    await screen.findByText('Tech Feed')
    fireEvent.click(screen.getByRole('button', { name: '「技术」分类操作' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '重命名分类' }))
    const input = await screen.findByLabelText('分类名')
    expect(input).toHaveValue('技术')
    fireEvent.change(input, { target: { value: 'Tech' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => {
      const patch = fetchState.calls.find(
        (c) => c.method === 'PATCH' && c.url.includes('/api/v1/categories/'),
      )
      expect(patch?.body).toEqual({ label: 'Tech' })
    })
    // invalidate → refetch → 新分组名出现，旧分组名消失
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: 'Tech，1 个订阅源' }),
      ).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: '技术，1 个订阅源' })).toBeNull()
  })

  it('分类被重命名后，旧 categoryId 的 scope 回退「全部」', async () => {
    useReaderUi.setState({
      scope: { kind: 'rss-category', categoryId: CAT_TECH.id, categoryLabel: '技术' },
    })
    renderPage()
    await screen.findByText('Tech Feed')
    fireEvent.click(screen.getByRole('button', { name: '「技术」分类操作' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '重命名分类' }))
    fireEvent.change(await screen.findByLabelText('分类名'), { target: { value: 'Tech' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => {
      expect(useReaderUi.getState().scope).toEqual({ kind: 'all' })
    })
  })

  it('默认分类不可重命名：409 → 诚实提示（前端不硬编码猜测默认分类）', async () => {
    const server = makeServer()
    server.routes[`PATCH /api/v1/categories/${encodeURIComponent(CAT_TECH.id)}`] = () =>
      jsonResponse(
        { error: { type: 'default_category_immutable', message: 'immutable' } },
        409,
      )
    renderPage(server)
    await screen.findByText('Tech Feed')
    fireEvent.click(screen.getByRole('button', { name: '「技术」分类操作' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '重命名分类' }))
    fireEvent.change(await screen.findByLabelText('分类名'), { target: { value: 'Tech' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    expect(
      await screen.findByText('默认分类由 FreshRSS 管理，无法重命名。'),
    ).toBeInTheDocument()
  })
})

describe('顶部动作与空态', () => {
  it('OPML 导入为真实入口（Gate 4，打开对话框）；分组管理占位已移除', async () => {
    renderPage()
    await screen.findByText('Tech Feed')
    expect(screen.queryByText('分组管理')).toBeNull()
    expect(screen.getByRole('button', { name: /添加来源/ })).not.toBeDisabled()
    const opml = screen.getByRole('button', { name: /导入 OPML/ })
    expect(opml).not.toBeDisabled()
    fireEvent.click(opml)
    expect(await screen.findByRole('dialog', { name: '导入 OPML' })).toBeInTheDocument()
    // 未选文件前无「确认导入」可点（严格 preview-before-mutation）
    expect(screen.getByRole('button', { name: '确认导入' })).toBeDisabled()
  })

  it('无订阅：空态（不编造示例源）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = String(input)
        if (url === '/api/v1/subscriptions') return jsonResponse([])
        if (url === '/api/v1/categories') return jsonResponse([CAT_DEFAULT])
        throw new Error(`unexpected fetch: ${url}`)
      }),
    )
    render(withProviders(<SubscriptionsPage />))
    expect(await screen.findByText('还没有订阅源')).toBeInTheDocument()
  })

  it('加载失败：错误状态 + 重试', async () => {
    let fail = true
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = String(input)
        if (url === '/api/v1/categories') return jsonResponse([CAT_TECH, CAT_DEFAULT])
        if (url === '/api/v1/subscriptions') {
          return fail
            ? jsonResponse({ error: { type: 'upstream_error', message: '上游不可用' } }, 502)
            : jsonResponse(SUBSCRIPTIONS)
        }
        throw new Error(`unexpected fetch: ${url}`)
      }),
    )
    render(withProviders(<SubscriptionsPage />))
    expect(await screen.findByText('订阅加载失败')).toBeInTheDocument()
    fail = false
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByText('Tech Feed')).toBeInTheDocument()
  })
})
