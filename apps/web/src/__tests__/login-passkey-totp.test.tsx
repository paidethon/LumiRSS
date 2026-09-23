/** N006 通行密钥 + N007 两步验证 — 登录面测试。
 *
 * 真实组件 + mocked fetch / navigator.credentials：passkey 入口仅在
 * login-options 报告可用时出现；passkey 登录走真实调用链；密码登录
 * 返回 totpRequired → 出现验证码步 → verify 换发会话；错误路径文案。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import LoginScreen from '../components/LoginScreen'
import { useAuthStore } from '../store/auth'

const fakeSecret = (prefix: string) => {
  const bytes = new Uint8Array(8)
  crypto.getRandomValues(bytes)
  return prefix + Array.from(bytes, (b) => b.toString(36).padStart(2, '0')).join('')
}
const PASSWORD = fakeSecret('correct-')
const TOKEN = fakeSecret('pending-')

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

/** base64url（测试值，非加密材料）。 */
const b64u = (value: string) => btoa(value).replace(/\+/g, '-').replace(/_/g, '_').replace(/=+$/, '')

function bytesOf(value: string): ArrayBuffer {
  const bytes = new TextEncoder().encode(value)
  return bytes.buffer as ArrayBuffer
}

/** 形状与 PublicKeyCredential 一致的假凭据（encodeAssertionResponse 可序列化）。 */
function fakeAssertionCredential() {
  return {
    id: b64u('cred-1'),
    rawId: bytesOf('cred-1'),
    type: 'public-key',
    authenticatorAttachment: 'platform',
    response: {
      clientDataJSON: bytesOf('client-data'),
      authenticatorData: bytesOf('auth-data'),
      signature: bytesOf('signature'),
      userHandle: bytesOf('u1'),
    },
    getClientExtensionResults: () => ({}),
  }
}

function fakeAttestationCredential() {
  return {
    id: b64u('cred-2'),
    rawId: bytesOf('cred-2'),
    type: 'public-key',
    response: {
      clientDataJSON: bytesOf('client-data-create'),
      attestationObject: bytesOf('attestation'),
      getTransports: () => ['internal'],
    },
    getClientExtensionResults: () => ({}),
  }
}

function stubWebauthnAvailable(overrides: { get?: ReturnType<typeof vi.fn>; create?: ReturnType<typeof vi.fn> } = {}) {
  // webauthnSupported() 以 typeof === 'function' 探测。
  Object.defineProperty(window, 'PublicKeyCredential', {
    configurable: true,
    value: function PublicKeyCredentialStub() {},
  })
  Object.defineProperty(navigator, 'credentials', {
    configurable: true,
    value: {
      get: overrides.get ?? vi.fn().mockResolvedValue(fakeAssertionCredential()),
      create: overrides.create ?? vi.fn().mockResolvedValue(fakeAttestationCredential()),
    },
  })
}

function renderLogin() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <LoginScreen />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useAuthStore.setState({ status: 'unauthenticated', mode: 'session', identity: null })
  localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  // 清掉 navigator/window 上的测试桩。
  Object.defineProperty(window, 'PublicKeyCredential', { configurable: true, value: undefined })
  Reflect.deleteProperty(navigator as unknown as Record<string, unknown>, 'credentials')
})

describe('N006 登录面通行密钥', () => {
  it('login-options 报告可用 → 显示「使用通行密钥」，点击走真实断言流程', async () => {
    stubWebauthnAvailable()
    const fetchMock = vi.fn().mockImplementation((url: string | URL) => {
      const target = String(url)
      if (target.endsWith('/auth/passkeys/login/options')) {
        return Promise.resolve(
          jsonResponse({
            publicKey: {
              challenge: b64u('challenge-1'),
              rpId: 'lumirss.test',
              allowCredentials: [{ id: b64u('cred-1'), type: 'public-key' }],
            },
            challenge: b64u('challenge-1'),
            passkeyAvailable: true,
          }),
        )
      }
      if (target.endsWith('/auth/passkeys/login')) {
        return Promise.resolve(
          jsonResponse({ authenticated: true, mode: 'session', expiresAt: '2099-01-01T00:00:00Z' }),
        )
      }
      if (target.endsWith('/auth/session')) {
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
      return Promise.resolve(jsonResponse({ authenticated: false, mode: 'session' }))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderLogin()
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'alice' } })
    const button = await screen.findByRole('button', { name: /使用通行密钥/ }, { timeout: 2500 })
    fireEvent.click(button)
    await waitFor(() => {
      expect(useAuthStore.getState().status).toBe('authenticated')
    })
    const loginCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/auth/passkeys/login'))!
    const body = JSON.parse(loginCall[1].body)
    expect(body.username).toBe('alice')
    expect(body.challenge).toBe(b64u('challenge-1'))
    expect(body.id).toBe(b64u('cred-1'))
    expect(useAuthStore.getState().identity?.username).toBe('alice')
  })

  it('passkeyAvailable=false（未知用户/无密钥）→ 入口不出现（无账号枚举）', async () => {
    stubWebauthnAvailable()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string | URL) => {
        if (String(url).endsWith('/auth/passkeys/login/options')) {
          return Promise.resolve(
            jsonResponse({
              publicKey: { challenge: b64u('c'), rpId: 'lumirss.test', allowCredentials: [] },
              challenge: b64u('c'),
              passkeyAvailable: false,
            }),
          )
        }
        return Promise.resolve(jsonResponse({ authenticated: false, mode: 'session' }))
      }),
    )
    renderLogin()
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'whoami' } })
    await waitFor(
      () => {
        expect(
          vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith('/auth/passkeys/login/options')),
        ).toBe(true)
      },
      { timeout: 2500 },
    )
    await new Promise((resolve) => setTimeout(resolve, 450))
    expect(screen.queryByRole('button', { name: /使用通行密钥/ })).not.toBeInTheDocument()
  })

  it('断言失败（服务端 401）→ 统一失败文案，不泄露细节', async () => {
    stubWebauthnAvailable()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string | URL) => {
        const target = String(url)
        if (target.endsWith('/auth/passkeys/login/options')) {
          return Promise.resolve(
            jsonResponse({
              publicKey: { challenge: b64u('c'), rpId: 'x', allowCredentials: [{ id: b64u('cred-1'), type: 'public-key' }] },
              challenge: b64u('c'),
              passkeyAvailable: true,
            }),
          )
        }
        if (target.endsWith('/auth/passkeys/login')) {
          return Promise.resolve(
            jsonResponse({ error: { type: 'invalid_credentials', message: '通行密钥验证失败。' } }, 401),
          )
        }
        return Promise.resolve(jsonResponse({ authenticated: false, mode: 'session' }))
      }),
    )
    renderLogin()
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'alice' } })
    const button = await screen.findByRole('button', { name: /使用通行密钥/ }, { timeout: 2500 })
    fireEvent.click(button)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('通行密钥验证失败')
    expect(useAuthStore.getState().status).toBe('unauthenticated')
  })
})

describe('N007 登录面两步验证', () => {
  function totpFetchMock(verifyResponse: () => Response) {
    return vi.fn().mockImplementation((url: string | URL) => {
      const target = String(url)
      if (target.endsWith('/auth/login')) {
        return Promise.resolve(jsonResponse({ totpRequired: true, pendingToken: TOKEN }))
      }
      if (target.endsWith('/auth/totp/verify')) {
        return Promise.resolve(verifyResponse())
      }
      if (target.endsWith('/auth/session')) {
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
      return Promise.resolve(jsonResponse({ authenticated: false, mode: 'session' }))
    })
  }

  it('密码正确但 TOTP 开启 → 进入验证码步，verify 成功后翻门', async () => {
    const fetchMock = totpFetchMock(() =>
      jsonResponse({ authenticated: true, mode: 'session', expiresAt: '2099-01-01T00:00:00Z' }),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderLogin()
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: PASSWORD } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))
    // 两步验证步出现，密码表单消失。
    const code = await screen.findByLabelText('验证码')
    expect(screen.queryByLabelText('密码')).not.toBeInTheDocument()
    expect(useAuthStore.getState().status).toBe('unauthenticated')
    // 未填验证码不能提交。
    expect(screen.getByRole('button', { name: /验证并登录/ })).toBeDisabled()
    fireEvent.change(code, { target: { value: '123456' } })
    fireEvent.click(screen.getByRole('button', { name: /验证并登录/ }))
    await waitFor(() => {
      expect(useAuthStore.getState().status).toBe('authenticated')
    })
    const verifyCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/auth/totp/verify'))!
    expect(JSON.parse(verifyCall[1].body)).toEqual({ pendingToken: TOKEN, code: '123456' })
    // 响应体里的 pending token 不落在任何输入框（不是会话也不回显）。
    expect(screen.queryByDisplayValue(TOKEN)).not.toBeInTheDocument()
  })

  it('错误验证码 → 「验证码无效」，停留验证码步', async () => {
    const fetchMock = totpFetchMock(() =>
      jsonResponse({ error: { type: 'totp_code_invalid', message: '验证码无效。' } }, 401),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderLogin()
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: PASSWORD } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))
    const code = await screen.findByLabelText('验证码')
    fireEvent.change(code, { target: { value: '000000' } })
    fireEvent.click(screen.getByRole('button', { name: /验证并登录/ }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('验证码无效')
    expect(useAuthStore.getState().status).toBe('unauthenticated')
    expect(screen.getByLabelText('验证码')).toBeInTheDocument()
  })

  it('pending token 过期 → 回到密码步并提示重新登录', async () => {
    const fetchMock = totpFetchMock(() =>
      jsonResponse({ error: { type: 'pending_token_invalid', message: '登录请求已过期，请重新登录。' } }, 401),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderLogin()
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: PASSWORD } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))
    const code = await screen.findByLabelText('验证码')
    fireEvent.change(code, { target: { value: '123456' } })
    fireEvent.click(screen.getByRole('button', { name: /验证并登录/ }))
    await waitFor(() => {
      expect(screen.getByLabelText('密码')).toBeInTheDocument()
    })
    expect(useAuthStore.getState().status).toBe('unauthenticated')
  })

  it('可切换恢复码输入', async () => {
    const fetchMock = totpFetchMock(() =>
      jsonResponse({ error: { type: 'totp_code_invalid', message: '验证码无效。' } }, 401),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderLogin()
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: PASSWORD } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))
    await screen.findByLabelText('验证码')
    fireEvent.click(screen.getByRole('button', { name: /使用恢复码/ }))
    expect(screen.getByLabelText('恢复码')).toBeInTheDocument()
    expect(screen.queryByLabelText('验证码')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /改用验证器验证码/ }))
    expect(screen.getByLabelText('验证码')).toBeInTheDocument()
  })
})
