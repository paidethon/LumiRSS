/** FIX-003 — /admin 路由闭环守卫（BASELINE_OK 钉定）。
 *
 * 台账前提：直接打开 /admin 后刷新、后退和重新登录应各自闭环，
 * 不落回阅读器空白页。核验结论（诚实证据）：闭环在基线已成立——
 * 1. 刷新：路由源 = location.pathname（readAppRoute），/admin 直接
 *    打开/刷新都判定为 admin（app-route.test.ts 已钉 pathname/hash 双源）；
 * 2. 后退：useAppRoute 以 useSyncExternalStore 订阅 popstate +
 *    自定义路由事件，AdminScreen「返回」= navigateAppRoute('app')，
 *    浏览器后退回到 /admin 时路由同步回 admin（本文件新钉 popstate 闭环）；
 * 3. 重新登录：未登录直开 /admin → AuthEntrance 回落 LoginScreen，
 *    登录成功 finishLogin 发现路由非 app → navigateAppRoute('app', true)
 *    落回应用首页（本文件新钉），绝不出现「已登录却停在无法渲染的
 *    路由」或空白页。
 * 本文件把这三段闭环作为廉价守卫钉死，防止未来路由改造破坏。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { navigateAppRoute, readAppRoute } from '../lib/app-route'
import { useAuthStore } from '../store/auth'
import LoginScreen from '../components/LoginScreen'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

/** 动态生成密码样本（套件约定：无凭据形状字面量）。 */
const PASSWORD = 'pw-' + Array.from(crypto.getRandomValues(new Uint8Array(8)), (b) => b.toString(36)).join('')

beforeEach(() => {
  localStorage.clear()
  useAuthStore.setState({ status: 'unauthenticated', mode: 'session', identity: null, probeNonce: 0 })
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', '/')
})

describe('FIX-003 /admin 路由闭环（BASELINE_OK 守卫）', () => {
  it('刷新闭环：pathname /admin → admin（刷新后同源判定不变）', () => {
    window.history.replaceState(null, '', '/admin')
    expect(readAppRoute()).toBe('admin')
  })

  it('后退闭环：admin →「返回」→ app → 浏览器后退 → 回 admin（popstate 同步）', async () => {
    window.history.replaceState(null, '', '/admin')
    expect(readAppRoute()).toBe('admin')
    // AdminScreen「返回阅读」按钮的同一调用（pushState，留历史）。
    navigateAppRoute('app')
    expect(window.location.pathname).toBe('/')
    expect(readAppRoute()).toBe('app')
    // 浏览器后退：popstate 送达订阅者，路由回 admin。
    const back = new Promise<void>((resolve) => {
      window.addEventListener('popstate', () => resolve(), { once: true })
    })
    window.history.back()
    await back
    expect(window.location.pathname).toBe('/admin')
    expect(readAppRoute()).toBe('admin')
  })

  it('重新登录闭环：未登录直开 /admin → 登录成功落回应用首页（不滞留 admin 路由）', async () => {
    window.history.replaceState(null, '', '/admin')
    const fetchMock = vi.fn().mockImplementation((url: string | URL) => {
      if (String(url).endsWith('/auth/session')) {
        return jsonResponse({
          authenticated: true,
          mode: 'session',
          userId: 'u1',
          username: 'alice',
          role: 'member',
        })
      }
      return jsonResponse({ authenticated: true, mode: 'session', expiresAt: '2099-01-01T00:00:00Z' })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(
      <QueryClientProvider client={new QueryClient()}>
        <LoginScreen />
      </QueryClientProvider>,
    )
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: PASSWORD } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))
    await waitFor(() => {
      expect(useAuthStore.getState().status).toBe('authenticated')
    })
    // finishLogin 的兜底导航：路由非 app → navigateAppRoute('app', true)。
    expect(window.location.pathname).toBe('/')
    expect(readAppRoute()).toBe('app')
  })
})
