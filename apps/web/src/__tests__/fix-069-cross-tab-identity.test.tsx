/** FIX-069 — 跨标签页身份切换：旧标签页不得继续以 A 的身份写入状态。
 *
 * 同一浏览器的所有标签页共享 session cookie 与 localStorage。B 在
 * 标签页 2 登录/登出后，标签页 1 若还挂着 A 的应用子树，会继续以
 * A 的内存状态运行并写入共享存储（最近阅读、草稿、设置 dirty……）。
 *
 * 契约：resetAccountState（一切登录/登出的统一出口）广播 auth epoch
 * （localStorage 键，storage 事件只送达其他标签页）；其他标签页的
 * AuthGate 收到后：清缓存与本机足迹 → 身份置空 → 回 checking 重新
 * 探测（shared cookie 已是新身份）→ 以新身份重挂应用。
 * 本标签页对事件的处理绝不再次广播（否则跨标签页乒乓循环）。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { AUTH_EPOCH_STORAGE_KEY, useAuthStore, type AuthIdentity } from '../store/auth'
import { useAuthGate } from '../lib/auth-gate'
import { recordRecentRead, listRecentReads } from '../lib/recent-reads'

const identityA: AuthIdentity = { userId: 'user-a', username: 'alice', role: 'owner' }
const identityB: AuthIdentity = { userId: 'user-b', username: 'bob', role: 'member' }

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

/** main.tsx AuthGate 的行为复刻（逻辑本体在 useAuthGate，生产与测试共用）。 */
function Gate(): React.ReactElement {
  const status = useAuthGate(new QueryClient({ defaultOptions: { queries: { retry: false } } }))
  if (status === 'checking') return <p role="status">正在核实身份…</p>
  if (status === 'unauthenticated') return <p role="status">登录入口</p>
  return (
    <p>
      {useAuthStore.getState().identity?.username ?? 'no-identity'} 的应用子树 ·{' '}
      {listRecentReads().length} 条最近阅读
    </p>
  )
}

function renderGate() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <Gate />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.unstubAllGlobals()
  useAuthStore.setState({ status: 'checking', mode: null, identity: null, probeNonce: 0 })
})

describe('FIX-069 跨标签页身份同步', () => {
  it('标签页 2 登录/登出（epoch 事件）→ 标签页 1 清足迹、重新探测，以新身份重挂', async () => {
    // 标签页 1：以 A 的身份运行，留有 A 的本机足迹。
    // 共享 cookie 的服务端真值随标签页 2 的登录切换为 B。
    let serverIdentity = identityA
    const fetchMock = vi.fn(async (url: unknown) => {
      if (String(url).endsWith('/auth/session')) return sessionProbe(serverIdentity)
      return jsonResponse({}, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderGate()
    await waitFor(() =>
      expect(screen.getByText(/alice 的应用子树/)).toBeInTheDocument(),
    )
    recordRecentRead({ entryRef: 'a-entry', feedTitle: 'A 的源', title: 'A 的文章' })
    expect(listRecentReads()).toHaveLength(1)

    // 标签页 2 完成了登录（服务端会话已是 B）→ epoch 广播送达标签页 1。
    serverIdentity = identityB
    window.dispatchEvent(
      new StorageEvent('storage', {
        key: AUTH_EPOCH_STORAGE_KEY,
        oldValue: 'old',
        newValue: 'new-epoch',
      }),
    )

    // 足迹立即清空（不能继续以 A 的身份写共享存储）……
    await waitFor(() => expect(listRecentReads()).toHaveLength(0))
    // ……门回 checking 并重新探测；共享 cookie 已是 B → 以 B 重挂。
    await waitFor(() => expect(screen.getByText(/bob 的应用子树/)).toBeInTheDocument())
    expect(useAuthStore.getState().identity?.username).toBe('bob')
    // 处理事件不再次广播（localStorage 里不会出现本标签页写入的 epoch）。
    expect(localStorage.getItem(AUTH_EPOCH_STORAGE_KEY)).toBeNull()
  })

  it('无关键的 storage 事件不触发身份重置；已非 authenticated 的标签页忽略 epoch', async () => {
    const fetchMock = vi.fn(async (url: unknown) => {
      if (String(url).endsWith('/auth/session')) return sessionProbe(identityA)
      return jsonResponse({}, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderGate()
    await waitFor(() =>
      expect(screen.getByText(/alice 的应用子树/)).toBeInTheDocument(),
    )
    recordRecentRead({ entryRef: 'a-entry', feedTitle: 'A 的源', title: 'A 的文章' })

    // 无关键：不影响身份与足迹。
    window.dispatchEvent(new StorageEvent('storage', { key: 'lumirss-recent-reads', newValue: '{}' }))
    expect(useAuthStore.getState().status).toBe('authenticated')
    expect(listRecentReads()).toHaveLength(1)

    // 已不是 authenticated（如自己在登录页）→ 忽略 epoch，不重置探测循环。
    useAuthStore.getState().setStatus('unauthenticated')
    const probeCalls = fetchMock.mock.calls.length
    window.dispatchEvent(
      new StorageEvent('storage', { key: AUTH_EPOCH_STORAGE_KEY, newValue: 'n2' }),
    )
    expect(useAuthStore.getState().status).toBe('unauthenticated')
    expect(fetchMock.mock.calls.length).toBe(probeCalls)
  })
})
