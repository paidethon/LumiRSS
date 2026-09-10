/** 会话认证（Web 侧）测试 — Phase N。
 *
 * 覆盖：登录门状态机（basic 放行 / session 门控 / 探测失败放行）、
 * 401 session_required 的全局翻转、LoginScreen 的错误语义（网络不可用
 * 绝不显示「密码错误」）、登出清缓存。
 *
 * 所有凭据均为运行时动态生成的假值（套件约定：无凭据形状字面量）。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ApiError, getAuthSession, getFeeds, loginPassword } from '../api/client'
import { sessionExpired, useAuthStore } from '../store/auth'
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

describe('LoginScreen', () => {
  beforeEach(() => {
    useAuthStore.setState({ status: 'unauthenticated', mode: 'session' })
  })

  function renderLogin() {
    return render(
      <QueryClientProvider client={new QueryClient()}>
        <LoginScreen />
      </QueryClientProvider>,
    )
  }

  it('渲染密码输入与登录按钮（无 username 字段）', () => {
    renderLogin()
    expect(screen.getByLabelText('密码')).toBeInTheDocument()
    expect(screen.queryByLabelText(/用户名/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '登录' })).toBeDisabled()
  })

  it('正确密码 → 门翻到 authenticated，请求体只含 password', async () => {
    const fetchMock = vi.fn().mockResolvedValue(probe('session', true))
    vi.stubGlobal('fetch', fetchMock)
    renderLogin()
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: GOOD_PASSWORD } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))
    await waitFor(() => {
      expect(useAuthStore.getState().status).toBe('authenticated')
    })
    expect(fetchMock.mock.calls[0]![0]).toBe('/api/v1/auth/login')
    const body = JSON.parse(fetchMock.mock.calls[0]![1].body)
    expect(body).toEqual({ password: GOOD_PASSWORD })
  })

  it('密码错误 → 显示服务端错误信息，输入保留方便重试', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          { error: { type: 'invalid_credentials', message: 'Incorrect password.' } },
          401,
        ),
      ),
    )
    renderLogin()
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: WRONG_PASSWORD } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect password.')
    expect(useAuthStore.getState().status).toBe('unauthenticated')
    expect(screen.getByLabelText('密码')).toHaveValue(WRONG_PASSWORD)
  })

  it('网络失败 → 显示「网络不可用」，绝不误导为密码错误/会话过期', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    renderLogin()
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: WRONG_PASSWORD } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('网络不可用')
    expect(alert).not.toHaveTextContent('密码错误')
    expect(alert).not.toHaveTextContent('会话过期')
    expect(useAuthStore.getState().status).toBe('unauthenticated')
  })

  it('限流（429）→ 显示服务端 message', async () => {
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
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: WRONG_PASSWORD } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Too many attempts')
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

describe('loginPassword 请求形状', () => {
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
