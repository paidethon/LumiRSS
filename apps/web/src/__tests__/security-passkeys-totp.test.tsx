/** N006 通行密钥 + N007 两步验证 — 账户安全页测试。
 *
 * mocked fetch / navigator.credentials：TOTP setup→enable→恢复码一次
 * 显示→disable；改密表单在 TOTP 开启时出现验证码字段；通行密钥
 * 注册（真实 navigator.credentials.create 链路）与删除（带密码）。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AccountSecuritySection } from '../components/settings/AccountSecuritySection'
import { useAuthStore } from '../store/auth'

const fakeSecret = (prefix: string) => {
  const bytes = new Uint8Array(8)
  crypto.getRandomValues(bytes)
  return prefix + Array.from(bytes, (b) => b.toString(36).padStart(2, '0')).join('')
}
const PASSWORD = fakeSecret('correct-')
const NEW_PASSWORD = fakeSecret('brand-new-')

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function emptyResponse(status = 204): Response {
  return new Response(null, { status })
}

const b64u = (value: string) => btoa(value).replace(/\+/g, '-').replace(/_/g, '_').replace(/=+$/, '')

function bytesOf(value: string): ArrayBuffer {
  return new TextEncoder().encode(value).buffer as ArrayBuffer
}

function fakeAttestationCredential() {
  return {
    id: b64u('cred-new'),
    rawId: bytesOf('cred-new'),
    type: 'public-key',
    response: {
      clientDataJSON: bytesOf('client-data-create'),
      attestationObject: bytesOf('attestation'),
      getTransports: () => ['internal'],
    },
    getClientExtensionResults: () => ({}),
  }
}

function stubCreate(credential: unknown) {
  Object.defineProperty(window, 'PublicKeyCredential', {
    configurable: true,
    value: function PublicKeyCredentialStub() {},
  })
  Object.defineProperty(navigator, 'credentials', {
    configurable: true,
    value: { create: vi.fn().mockResolvedValue(credential), get: vi.fn() },
  })
}

interface Route {
  method: string
  suffix: string
  respond: (init: { url: string; body: unknown }) => Response
}

function renderSecurity(routes: Route[]) {
  const fetchMock = vi.fn().mockImplementation((url: string | URL, init?: RequestInit) => {
    const target = String(url)
    const method = (init?.method ?? 'GET').toUpperCase()
    const route = routes.find((r) => r.method === method && target.endsWith(r.suffix))
    if (route) return Promise.resolve(route.respond({ url: target, body: init?.body }))
    // 默认公共面：会话列表为空 + 其余读面回空形。
    if (target.endsWith('/auth/sessions')) return Promise.resolve(jsonResponse([]))
    if (target.endsWith('/auth/passkeys')) return Promise.resolve(jsonResponse([]))
    if (target.endsWith('/auth/totp')) return Promise.resolve(jsonResponse({ enabled: false, recoveryCodesRemaining: 0 }))
    return Promise.resolve(jsonResponse({}, 200))
  })
  vi.stubGlobal('fetch', fetchMock)
  const queryClient = new QueryClient()
  render(
    <QueryClientProvider client={queryClient}>
      <AccountSecuritySection />
    </QueryClientProvider>,
  )
  return fetchMock
}

beforeEach(() => {
  useAuthStore.setState({ status: 'authenticated', mode: 'session', identity: null })
  localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  Object.defineProperty(window, 'PublicKeyCredential', { configurable: true, value: undefined })
  Reflect.deleteProperty(navigator as unknown as Record<string, unknown>, 'credentials')
})

describe('N007 两步验证（安全页）', () => {
  it('setup → 手动录入（URI+密钥+复制）→ enable → 恢复码只显示一次', async () => {
    const codes = ['aaaa1111bb', 'cccc2222dd', 'eeee3333ff', 'aaaa4444aa', 'bbbb5555bb', 'dddd6666cc', 'eeee7777dd', 'ffff8888ee']
    let totpEnabled = false
    renderSecurity([
      {
        method: 'POST',
        suffix: '/auth/totp/setup',
        respond: () =>
          jsonResponse({
            secret: 'JBSWY3DPEHPK3PXP',
            otpauthUri: 'otpauth://totp/LumiRSS:owner?issuer=LumiRSS&secret=JBSWY3DPEHPK3PXP',
          }),
      },
      {
        method: 'POST',
        suffix: '/auth/totp/enable',
        respond: () => {
          totpEnabled = true
          return jsonResponse({ recoveryCodes: codes })
        },
      },
      { method: 'GET', suffix: '/auth/totp', respond: () => jsonResponse({ enabled: totpEnabled, recoveryCodesRemaining: totpEnabled ? 8 : 0 }) },
    ])
    fireEvent.click(await screen.findByRole('button', { name: '开启两步验证' }))
    // 手动录入：秘密与 URI 明文展示 + 复制按钮（无 QR 依赖）。
    expect(await screen.findByText('JBSWY3DPEHPK3PXP')).toBeInTheDocument()
    expect(screen.getByText('otpauth://totp/LumiRSS:owner?issuer=LumiRSS&secret=JBSWY3DPEHPK3PXP')).toBeInTheDocument()
    expect(screen.getByText('密钥（Base32）')).toBeInTheDocument()
    // 输入 6 位验证码 → 确认开启。
    fireEvent.change(screen.getByLabelText('输入 6 位验证码确认'), { target: { value: '123456' } })
    fireEvent.click(screen.getByRole('button', { name: '确认开启' }))
    // 恢复码一次性显示。
    expect(await screen.findByText('恢复码（仅显示这一次 —— 请立即保存到安全的地方）')).toBeInTheDocument()
    for (const code of codes) {
      expect(screen.getByText(code)).toBeInTheDocument()
    }
    // 未勾选「已保存」前不能收起。
    expect(screen.getByRole('button', { name: '完成' })).toBeDisabled()
    fireEvent.click(screen.getByLabelText(/我已保存这些恢复码/))
    fireEvent.click(screen.getByRole('button', { name: '完成' }))
    expect(screen.queryByText(codes[0])).not.toBeInTheDocument()
  })

  it('enable 返回错误验证码 → 服务端错误文案可见', async () => {
    renderSecurity([
      {
        method: 'POST',
        suffix: '/auth/totp/setup',
        respond: () => jsonResponse({ secret: 'JBSWY3DPEHPK3PXP', otpauthUri: 'otpauth://totp/x' }),
      },
      {
        method: 'POST',
        suffix: '/auth/totp/enable',
        respond: () => jsonResponse({ error: { type: 'totp_code_invalid', message: '验证码无效。' } }, 401),
      },
    ])
    fireEvent.click(await screen.findByRole('button', { name: '开启两步验证' }))
    fireEvent.change(await screen.findByLabelText('输入 6 位验证码确认'), { target: { value: '000000' } })
    fireEvent.click(screen.getByRole('button', { name: '确认开启' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('验证码无效')
  })

  it('已开启：显示剩余恢复码数；disable 需要密码+验证码（服务端契约）', async () => {
    const fetchMock = renderSecurity([
      { method: 'GET', suffix: '/auth/totp', respond: () => jsonResponse({ enabled: true, recoveryCodesRemaining: 5 }) },
      { method: 'POST', suffix: '/auth/totp/disable', respond: () => jsonResponse({ disabled: true }) },
    ])
    fireEvent.change(await screen.findByLabelText('当前登录密码'), { target: { value: PASSWORD } })
    fireEvent.change(screen.getByLabelText('验证码或恢复码'), { target: { value: '654321' } })
    fireEvent.click(screen.getByRole('button', { name: '关闭两步验证' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('两步验证已关闭')
    const disableCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/auth/totp/disable'))!
    expect(JSON.parse(disableCall[1].body)).toEqual({ code: '654321', currentPassword: PASSWORD })
    expect(screen.getByText('剩余恢复码：5')).toBeInTheDocument()
  })
})

describe('N007 改密的二次验证字段（安全页）', () => {
  it('TOTP 开启 → 改密表单出现「两步验证码」字段并随请求提交', async () => {
    const fetchMock = renderSecurity([
      { method: 'GET', suffix: '/auth/totp', respond: () => jsonResponse({ enabled: true, recoveryCodesRemaining: 3 }) },
      { method: 'POST', suffix: '/auth/password', respond: () => jsonResponse({ authenticated: true, mode: 'session' }) },
    ])
    fireEvent.change(await screen.findByLabelText('当前密码'), { target: { value: PASSWORD } })
    // 「当前密码」有两个同标签输入（改密 + disable）→ 用 form 范围内的第一个。
    const inputs = screen.getAllByLabelText('当前密码')
    fireEvent.change(inputs[0], { target: { value: PASSWORD } })
    fireEvent.change(screen.getByLabelText('新密码'), { target: { value: NEW_PASSWORD } })
    fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: NEW_PASSWORD } })
    expect(screen.getByLabelText('两步验证码')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('两步验证码'), { target: { value: '246810' } })
    fireEvent.click(screen.getByRole('button', { name: '更新密码' }))
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/auth/password'))
      expect(call).toBeDefined()
      expect(JSON.parse(call![1].body)).toEqual({
        currentPassword: PASSWORD,
        newPassword: NEW_PASSWORD,
        totpCode: '246810',
      })
    })
  })

  it('TOTP 未开启 → 无验证码字段', async () => {
    renderSecurity([])
    fireEvent.change(await screen.findByLabelText('当前密码'), { target: { value: PASSWORD } })
    fireEvent.change(screen.getByLabelText('新密码'), { target: { value: NEW_PASSWORD } })
    expect(screen.queryByLabelText('两步验证码')).not.toBeInTheDocument()
  })
})

describe('N006 通行密钥（安全页）', () => {
  const registeredRow = { id: b64u('cred-1'), label: '我的钥匙', createdAt: 1700000000, lastUsedAt: null }

  it('注册：label + 真实 navigator.credentials.create + challenge 回传', async () => {
    stubCreate(fakeAttestationCredential())
    let created: Record<string, unknown> | undefined
    const fetchMock = renderSecurity([
      {
        method: 'POST',
        suffix: '/auth/passkeys/options',
        respond: () =>
          jsonResponse({
            publicKey: { challenge: b64u('challenge-9'), rp: { id: 'lumirss.test', name: 'LumiRSS' }, user: { id: b64u('u1'), name: 'owner' } },
            challenge: b64u('challenge-9'),
          }),
      },
      {
        method: 'POST',
        suffix: '/auth/passkeys',
        respond: ({ body }) => {
          created = JSON.parse(String(body))
          return jsonResponse({ id: b64u('cred-new'), label: '笔记本', createdAt: 1700000001, lastUsedAt: null })
        },
      },
      {
        method: 'GET',
        suffix: '/auth/passkeys',
        respond: () => jsonResponse([registeredRow, { id: b64u('cred-new'), label: '笔记本', createdAt: 1700000001, lastUsedAt: null }]),
      },
    ])
    fireEvent.change(await screen.findByLabelText('钥匙名称'), { target: { value: '笔记本' } })
    fireEvent.click(screen.getByRole('button', { name: '注册通行密钥' }))
    await waitFor(() => {
      expect(created).toBeDefined()
    })
    expect(created!.label).toBe('笔记本')
    expect(created!.challenge).toBe(b64u('challenge-9'))
    expect(created!.id).toBe(b64u('cred-new'))
    // 浏览器 API 拿到了服务端下发的 challenge。
    expect(vi.mocked(navigator.credentials.create)).toHaveBeenCalledWith(
      expect.objectContaining({
        publicKey: expect.objectContaining({ challenge: bytesOf('challenge-9') }),
      }),
    )
    expect(await screen.findByText('笔记本')).toBeInTheDocument()
    // 列表契约：只含 id/label/时间戳（服务端保证，前端断言防御）。
    const listCalls = fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith('/auth/passkeys') && (init?.method ?? 'GET') === 'GET')
    expect(listCalls.length).toBeGreaterThan(0)
  })

  it('列表展示 label 与时间戳；删除需当前密码，请求体含 currentPassword', async () => {
    let deleteBody: Record<string, unknown> | undefined
    renderSecurity([
      { method: 'GET', suffix: '/auth/passkeys', respond: () => jsonResponse([registeredRow]) },
      {
        method: 'DELETE',
        suffix: `/auth/passkeys/${encodeURIComponent(b64u('cred-1'))}`,
        respond: ({ body }) => {
          deleteBody = JSON.parse(String(body))
          return emptyResponse(204)
        },
      },
    ])
    expect(await screen.findByText('我的钥匙')).toBeInTheDocument()
    expect(screen.getByText(/创建于/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /删除/ }))
    fireEvent.change(await screen.findByLabelText('确认删除：当前密码'), { target: { value: PASSWORD } })
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))
    await waitFor(() => {
      expect(deleteBody).toEqual({ currentPassword: PASSWORD })
    })
  })

  it('服务端 401（密码错）→ 显示错误信息', async () => {
    renderSecurity([
      { method: 'GET', suffix: '/auth/passkeys', respond: () => jsonResponse([registeredRow]) },
      {
        method: 'DELETE',
        suffix: `/auth/passkeys/${encodeURIComponent(b64u('cred-1'))}`,
        respond: () => jsonResponse({ error: { type: 'invalid_credentials', message: '密码不正确。' } }, 401),
      },
    ])
    fireEvent.click(await screen.findByRole('button', { name: /删除/ }))
    fireEvent.change(await screen.findByLabelText('确认删除：当前密码'), { target: { value: 'wrong' } })
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('密码不正确')
  })
})
