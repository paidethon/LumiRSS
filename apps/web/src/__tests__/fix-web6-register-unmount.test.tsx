/** R2 web6 — FIX-289：表单卸载后的保存回调不导航。
 *
 * RegisterScreen 的提交成功回调会核实会话 → 落地身份 → 翻门导航。
 * 请求在途时表单被卸载（如用户点「返回登录」），晚到的成功结果必须
 * 丢弃：不落地身份状态、不导航到过期目标——请求结果只作用于仍有效的
 * 编辑会话。
 *
 * stub fetch（无真实网络）；api/client 走真实模块。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import RegisterScreen from '../components/RegisterScreen'
import { useAuthStore } from '../store/auth'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function withProviders(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>
}

function deferred<T>(): { promise: Promise<T>; resolve: (v: T) => void } {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

beforeEach(() => {
  useAuthStore.setState({ status: 'unauthenticated', mode: 'session', identity: null })
  localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', '/')
  vi.clearAllMocks()
})

describe('FIX-289 RegisterScreen 卸载守卫', () => {
  it('注册请求在途时表单卸载：晚到的成功结果不翻门（身份状态不落地）', async () => {
    const slowRegister = deferred<Response>()
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/api/v1/auth/register') && init?.method === 'POST') {
        return slowRegister.promise
      }
      throw new Error(`unexpected fetch: ${init?.method ?? 'GET'} ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const { unmount } = render(withProviders(<RegisterScreen />))

    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'newbie' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'Str0ng-enough-pw' } })
    fireEvent.change(screen.getByLabelText('确认密码'), { target: { value: 'Str0ng-enough-pw' } })
    fireEvent.click(screen.getByRole('button', { name: '注册并进入' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())

    // 用户在请求在途时离开表单（例如点「返回登录」触发的卸载）
    unmount()

    slowRegister.resolve(jsonResponse({ authenticated: true }))
    // 让微任务队列跑完（成功回调若不设防会在这里落地身份 + 导航）
    await new Promise((resolve) => setTimeout(resolve, 0))
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(useAuthStore.getState().status).toBe('unauthenticated')
    expect(useAuthStore.getState().identity).toBeNull()
    expect(window.location.pathname).toBe('/')
  })
})
