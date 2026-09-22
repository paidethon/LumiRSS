/** 会话认证（Web 侧）测试 — Phase N + 0067 多账户。
 *
 * 覆盖：登录门状态机（basic 放行 / session 门控 / 探测失败放行）、
 * 401 session_required 的全局翻转、LoginScreen 的多账户登录契约
 * （username+password；invalid_credentials 统一文案不做账号枚举；
 * rate_limited 显示剩余等待；网络不可用绝不误导）、身份归一。
 *
 * 所有凭据均为运行时动态生成的假值（套件约定：无凭据形状字面量）。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ApiError, getAuthSession, getFeeds, loginAccount, loginPassword } from '../api/client'
import { identityFromSession, sessionExpired, useAuthStore } from '../store/auth'
import LoginScreen from '../components/LoginScreen'

// 测试假值生成（非加密用途，但统一走 WebCrypto 避免弱随机告警）。
const fakeSecret = (prefix: string) => {
  const bytes = new Uint8Array(8)
  crypto.getRandomValues(bytes)
  return prefix + Array.from(bytes, (b) => b.toString(36).padStart(2, '0')).join('')
}
const GOOD_PASSWORD = fakeSecret('correct-')
const WRONG_PASSWORD = fakeSecret('wrong-')

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function probe(mode: 'basic' | 'session', authenticated: boolean) {
  return jsonResponse({
    authenticated,
    mode,
    ...(authenticated ? { expiresAt: '2099-01-01T00:00:00Z' } : {}),
  })
}

function resetAuthStore(mode: 'basic' | 'session' | null = 'session') {
  useAuthStore.setState({ status: 'authenticated', mode })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('401 session_required 翻转登录门', () => {
  beforeEach(() => resetAuthStore('session'))

  it('401 + session_required → 门翻到 unauthenticated', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ error: { type: 'session_required', message: 'Login required.' } }, 401),
      ),
    )
    await expect(getFeeds()).rejects.toBeInstanceOf(ApiError)
    expect(useAuthStore.getState().status).toBe('unauthenticated')
  })

  it('basic 模式的普通 401（无 session_required）不触发翻转', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ error: { type: 'http_error', message: 'unauthorized' } }, 401),
      ),
    )
    await expect(getFeeds()).rejects.toBeInstanceOf(ApiError)
    expect(useAuthStore.getState().status).toBe('authenticated')
  })

  it('sessionExpired 在 basic 模式下是 no-op', () => {
    resetAuthStore('basic')
    sessionExpired()
    expect(useAuthStore.getState().status).toBe('authenticated')
  })

  it('sessionExpired 幂等（重复调用不循环）', () => {
    resetAuthStore('session')
    sessionExpired()
    sessionExpired()
    expect(useAuthStore.getState().status).toBe('unauthenticated')
  })
})

describe('LoginScreen（0067 多账户）', () => {
  beforeEach(() => {
    useAuthStore.setState({ status: 'unauthenticated', mode: 'session', identity: null })
    localStorage.clear()
  })

  function renderLogin() {
    return render(
      <QueryClientProvider client={new QueryClient()}>
        <LoginScreen />
      </QueryClientProvider>,
    )
  }

  it('渲染用户名与密码输入；两项都填了才能提交', () => {
    renderLogin()
    expect(screen.getByLabelText('用户名')).toBeInTheDocument()
    expect(screen.getByLabelText('密码')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '登录' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'alice' } })
    expect(screen.getByRole('button', { name: '登录' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: GOOD_PASSWORD } })
    expect(screen.getByRole('button', { name: '登录' })).toBeEnabled()
  })

  it('正确凭据 → 门翻到 authenticated，请求体含 username+password，身份由 session 探测补齐', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string | URL) => {
      if (String(url).endsWith('/auth/session')) {
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
      return Promise.resolve(probe('session', true))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderLogin()
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: GOOD_PASSWORD } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))
    await waitFor(() => {
      expect(useAuthStore.getState().status).toBe('authenticated')
    })
    const loginCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/auth/login'))!
    expect(loginCall[0]).toBe('/api/v1/auth/login')
    expect(JSON.parse(loginCall[1].body)).toEqual({ username: 'alice', password: GOOD_PASSWORD })
    expect(useAuthStore.getState().identity).toEqual({
      userId: 'u1',
      username: 'alice',
      role: 'member',
    })
  })

  it('凭据错误 → 统一「用户名或密码不正确」，不透传服务端细节（无账号枚举）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          { error: { type: 'invalid_credentials', message: 'Incorrect username or password.' } },
          401,
        ),
      ),
    )
    renderLogin()
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: WRONG_PASSWORD } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('用户名或密码不正确')
    expect(alert).not.toHaveTextContent('Incorrect')
    expect(useAuthStore.getState().status).toBe('unauthenticated')
    // 输入保留方便重试
    expect(screen.getByLabelText('密码')).toHaveValue(WRONG_PASSWORD)
  })

  it('网络失败 → 显示「网络不可用」，绝不误导为密码错误/会话过期', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    renderLogin()
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: WRONG_PASSWORD } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('网络不可用')
    expect(alert).not.toHaveTextContent('密码错误')
    expect(alert).not.toHaveTextContent('会话过期')
    expect(useAuthStore.getState().status).toBe('unauthenticated')
  })

  it('限流（429 + Retry-After）→ 显示剩余等待秒数', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ error: { type: 'rate_limited', message: 'Too many attempts; wait a minute.' } }),
          {
            status: 429,
            headers: { 'content-type': 'application/json', 'Retry-After': '42' },
          },
        ),
      ),
    )
    renderLogin()
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: WRONG_PASSWORD } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('尝试过于频繁')
    expect(alert).toHaveTextContent('42')
  })

  it('限流（429 无 Retry-After 头）→ 仍显示限流提示，不编造秒数', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          { error: { type: 'rate_limited', message: 'Too many attempts; wait a minute.' } },
          429,
        ),
      ),
    )
    renderLogin()
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: WRONG_PASSWORD } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('尝试过于频繁')
    expect(alert).not.toHaveTextContent('秒后再试')
  })
})

describe('探测契约（AuthGate 行为的纯逻辑部分）', () => {
  it('basic 模式探测结果如实上报 mode', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(probe('basic', true)))
    const result = await getAuthSession()
    expect(result.mode).toBe('basic')
  })

  it('session 模式未登录探测结果', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(probe('session', false)))
    const result = await getAuthSession()
    expect(result.mode).toBe('session')
    expect(result.authenticated).toBe(false)
  })
})

describe('loginPassword 请求形状（legacy 兼容：basic 模式代理层凭据）', () => {
  it('POST /api/v1/auth/login，JSON body 只含 password', async () => {
    resetAuthStore('session')
    const fetchMock = vi.fn().mockResolvedValue(probe('session', true))
    vi.stubGlobal('fetch', fetchMock)
    await loginPassword(GOOD_PASSWORD)
    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/v1/auth/login')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ password: GOOD_PASSWORD })
  })
})

describe('loginAccount 请求形状（0067 多账户）', () => {
  it('POST /api/v1/auth/login，JSON body 含 username + password', async () => {
    resetAuthStore('session')
    const fetchMock = vi.fn().mockResolvedValue(probe('session', true))
    vi.stubGlobal('fetch', fetchMock)
    await loginAccount('alice', GOOD_PASSWORD)
    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/v1/auth/login')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ username: 'alice', password: GOOD_PASSWORD })
  })
})

describe('identityFromSession（身份归一）', () => {
  it('完整身份字段 → AuthIdentity', () => {
    expect(identityFromSession({ userId: 'u1', username: 'alice', role: 'admin' })).toEqual({
      userId: 'u1',
      username: 'alice',
      role: 'admin',
    })
  })
  it('缺字段 / 非法 role → null（账号菜单隐藏，绝不猜测身份）', () => {
    expect(identityFromSession({})).toBeNull()
    expect(identityFromSession({ userId: 'u1', username: 'alice', role: 'superuser' })).toBeNull()
    expect(identityFromSession({ userId: '', username: 'alice', role: 'member' })).toBeNull()
    expect(identityFromSession({ userId: 'u1', username: '', role: 'member' })).toBeNull()
  })
})
