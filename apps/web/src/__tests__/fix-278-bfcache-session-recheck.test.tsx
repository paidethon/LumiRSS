/**
 * FIX-278 — bfcache（back-forward cache）恢复后身份复核。
 *
 * 场景：用户登出后离开（或服务端撤销/过期了会话），浏览器 Back/前进
 * 恢复 bfcache 快照——JS 状态原样复活，此前没有任何恢复时点的会话重
 * 探：私有内容（缓存的文章/订阅）可以继续交互。
 *
 * 契约（与本仓既有语义一致）：
 * - pageshow persisted=true（bfcache 恢复）且当前 authenticated →
 *   先回 checking（AuthGate 摘下应用子树，私有交互暂停），再重新探测
 *   /auth/session，按探测结果放行（同 FIX-069 重探路径）；
 * - persisted=false（普通加载）不触发重探；
 * - 非 authenticated（已在登录页/探测中）不触发；
 * - 探测失败（离线）→ 放行：「连不上」不冒充「未登录」（Phase O）。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'

import { useAuthStore, type AuthIdentity } from '../store/auth'
import { useAuthGate } from '../lib/auth-gate'

const identityA: AuthIdentity = { userId: 'user-a', username: 'alice', role: 'owner' }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function sessionProbe(identity: AuthIdentity) {
  return jsonResponse({
    authenticated: true,
    mode: 'session',
    expiresAt: '2099-01-01T00:00:00Z',
    userId: identity.userId,
    username: identity.username,
    role: identity.role,
  })
}

function Gate(): React.ReactElement {
  const status = useAuthGate(new QueryClient({ defaultOptions: { queries: { retry: false } } }))
  if (status === 'checking') return <p role="status">正在核实身份…</p>
  if (status === 'unauthenticated') return <p role="status">登录入口</p>
  return <p>应用子树（{useAuthStore.getState().identity?.username ?? 'no-identity'}）</p>
}

function renderGate() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <Gate />
    </QueryClientProvider>,
  )
}

function firePageshow(persisted: boolean): void {
  window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted }))
}

beforeEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
  useAuthStore.setState({ status: 'checking', mode: null, identity: null, probeNonce: 0 })
})

describe('FIX-278: bfcache 恢复先复核会话再恢复私有交互', () => {
  it('persisted pageshow：先回 checking（摘下应用子树），重探通过后以已核实身份重挂', async () => {
    let sessionAlive = true
    const fetchMock = vi.fn(async (url: unknown) => {
      if (String(url).endsWith('/auth/session')) {
        return sessionAlive
          ? sessionProbe(identityA)
          : jsonResponse({ authenticated: false, mode: 'session' })
      }
      return jsonResponse({}, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderGate()
    await waitFor(() => expect(screen.getByText(/应用子树（alice）/)).toBeInTheDocument())
    const probesAfterBoot = fetchMock.mock.calls.length

    // 用户离开（会话在离开期间被服务端撤销）→ Back 恢复 bfcache 快照。
    sessionAlive = false
    firePageshow(true)

    // 先回 checking：私有应用子树被摘下（不能带着旧身份继续交互）。
    await waitFor(() => expect(screen.getByText('正在核实身份…')).toBeInTheDocument())
    // 重探执行（probeNonce 驱动的新探测请求）。
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(probesAfterBoot))
    // 服务端已未认证 → 门落到登录入口（缓存由既有 effect 清空）。
    await waitFor(() => expect(screen.getByText('登录入口')).toBeInTheDocument())
    expect(useAuthStore.getState().status).toBe('unauthenticated')
  })

  it('重探通过 → checking 短暂后恢复 authenticated（私有交互在复核后才可用）', async () => {
    const fetchMock = vi.fn(async (url: unknown) => {
      if (String(url).endsWith('/auth/session')) return sessionProbe(identityA)
      return jsonResponse({}, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderGate()
    await waitFor(() => expect(screen.getByText(/应用子树（alice）/)).toBeInTheDocument())
    const probesAfterBoot = fetchMock.mock.calls.length

    firePageshow(true)
    await waitFor(() => expect(screen.getByText('正在核实身份…')).toBeInTheDocument())
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(probesAfterBoot))
    await waitFor(() => expect(screen.getByText(/应用子树（alice）/)).toBeInTheDocument())
    expect(useAuthStore.getState().status).toBe('authenticated')
  })

  it('persisted=false（普通加载）与非 authenticated 状态都不触发重探', async () => {
    const fetchMock = vi.fn(async (url: unknown) => {
      if (String(url).endsWith('/auth/session')) return sessionProbe(identityA)
      return jsonResponse({}, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderGate()
    await waitFor(() => expect(screen.getByText(/应用子树（alice）/)).toBeInTheDocument())
    const probesAfterBoot = fetchMock.mock.calls.length

    // 普通导航返回（非 bfcache）→ 不重探、不摘子树。
    firePageshow(false)
    expect(useAuthStore.getState().status).toBe('authenticated')
    expect(fetchMock.mock.calls.length).toBe(probesAfterBoot)

    // 已在登录页（非 authenticated）→ 忽略 bfcache 恢复，不进探测循环。
    useAuthStore.setState({ status: 'unauthenticated' })
    firePageshow(true)
    expect(useAuthStore.getState().status).toBe('unauthenticated')
    expect(fetchMock.mock.calls.length).toBe(probesAfterBoot)
  })

  it('恢复时离线（探测失败）→ 放行：连不上不冒充未登录', async () => {
    // 启动探测成功；bfcache 恢复后的复核探测失败（网络故障）。
    let probeCount = 0
    const fetchMock = vi.fn(async (url: unknown) => {
      if (String(url).endsWith('/auth/session')) {
        probeCount += 1
        if (probeCount === 1) return sessionProbe(identityA)
        return Promise.reject(new TypeError('network'))
      }
      return jsonResponse({}, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderGate()
    await waitFor(() => expect(screen.getByText(/应用子树（alice）/)).toBeInTheDocument())
    const probesAfterBoot = fetchMock.mock.calls.length

    firePageshow(true)
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(probesAfterBoot))
    // 离线探测失败 → 恢复 authenticated（数据层诚实展示网络错误），
    // 且已核实身份保持不变（不冒充未登录、不清身份）。
    await waitFor(() => expect(useAuthStore.getState().status).toBe('authenticated'))
    expect(useAuthStore.getState().identity?.username).toBe('alice')
    expect(screen.getByText(/应用子树（alice）/)).toBeInTheDocument()
  })
})
