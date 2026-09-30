/** FIX-004 — 未登录身份初始化顺序守卫（BASELINE_OK 钉定）。
 *
 * 台账前提：未登录时不应先请求私有数据（文章/订阅）再闪现登录页。
 * 核验结论（诚实证据）：基线已按正确顺序实现——main.tsx 的 AuthGate
 * （行为本体 lib/auth-gate.ts）在 'checking' 期间只渲染启动 splash、
 * 不挂应用子树；探测返回未认证 → 渲染 AuthEntrance（登录/激活/注册），
 * 应用子树仍不挂载。TanStack Query 的消费组件全部位于应用子树内，
 * 因此私有查询只可能在 authenticated 之后发出。本文件以行为测试钉死：
 * 探测悬而未决 → 零私有请求；探测未认证 → 仍零私有请求；认证成功后
 * 子树挂载、私有查询才发出。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { useAuthStore } from '../store/auth'
import { useAuthGate } from '../lib/auth-gate'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

/** 门控宿主：authenticated 后挂一个会立即发私有查询（/feeds）的子树，
 * 与 main.tsx「AuthGate 包住 App」的结构同构。 */
function Gate(): React.ReactElement {
  const status = useAuthGate(new QueryClient({ defaultOptions: { queries: { retry: false } } }))
  if (status === 'checking') return <p role="status">启动中</p>
  if (status === 'unauthenticated') return <p role="status">登录入口</p>
  return <p>应用子树</p>
}

function PrivateProbe(): React.ReactElement {
  // 模拟应用子树内的私有查询消费方：挂载即请求。
  void fetch('/api/v1/feeds')
  return <p>应用子树</p>
}

function GateWithPrivateChild(): React.ReactElement {
  const status = useAuthGate(new QueryClient({ defaultOptions: { queries: { retry: false } } }))
  if (status === 'checking') return <p role="status">启动中</p>
  if (status === 'unauthenticated') return <p role="status">登录入口</p>
  return <PrivateProbe />
}

beforeEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
  useAuthStore.setState({ status: 'checking', mode: null, identity: null, probeNonce: 0 })
})

describe('FIX-004 门控先于私有查询（BASELINE_OK 守卫）', () => {
  it('探测悬而未决 → 停在 checking，应用子树不挂载，零私有请求', async () => {
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        calls.push(String(input))
        if (String(input).endsWith('/auth/session')) {
          return new Promise(() => {}) // 永不 resolve：探测悬而未决
        }
        return Promise.resolve(jsonResponse({ items: [], nextCursor: null }))
      }),
    )
    render(
      <QueryClientProvider client={new QueryClient()}>
        <Gate />
      </QueryClientProvider>,
    )
    expect(screen.getByRole('status')).toHaveTextContent('启动中')
    // 子树未挂载（无应用内容）；唯一发出的请求是公开的 /auth/session 探测。
    await waitFor(() => expect(calls).toEqual(['/api/v1/auth/session']))
    expect(screen.queryByText('应用子树')).not.toBeInTheDocument()
  })

  it('探测返回未认证 → 登录入口，应用子树仍不挂载，私有查询零发出', async () => {
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        calls.push(String(input))
        if (String(input).endsWith('/auth/session')) {
          return Promise.resolve(jsonResponse({ authenticated: false, mode: 'session' }))
        }
        return Promise.resolve(jsonResponse({ items: [], nextCursor: null }))
      }),
    )
    render(
      <QueryClientProvider client={new QueryClient()}>
        <GateWithPrivateChild />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('登录入口'))
    // 没有任何私有端点在登录前被请求（只多不了 /feeds）。
    expect(calls.filter((url) => !url.endsWith('/auth/session'))).toEqual([])
    expect(screen.queryByText('应用子树')).not.toBeInTheDocument()
  })

  it('探测返回已认证 → 应用子树挂载，私有查询此时才发出', async () => {
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        calls.push(String(input))
        if (String(input).endsWith('/auth/session')) {
          return Promise.resolve(
            jsonResponse({
              authenticated: true,
              mode: 'session',
              userId: 'u1',
              username: 'alice',
              role: 'member',
            }),
          )
        }
        return Promise.resolve(jsonResponse({ items: [], nextCursor: null }))
      }),
    )
    render(
      <QueryClientProvider client={new QueryClient()}>
        <GateWithPrivateChild />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(screen.getByText('应用子树')).toBeInTheDocument())
    expect(useAuthStore.getState().identity?.username).toBe('alice')
    expect(calls).toContain('/api/v1/feeds')
  })
})
