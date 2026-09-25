/** N005 密码强度本地评估 + N008 最近登录 — 安全页 / 纯函数测试。
 *
 * N005：scorer 类别覆盖（弱/中/强、连击/序列惩罚、空串）；改密表单
 * 的强度条随输入渲染；全程断言零网络请求（fetch 只被登录态读面调用，
 * 强度评估不触发任何额外 fetch）。
 * N008：最近登录面板（新设备徽标 / 批量标记已读 / 空态不渲染）。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AccountSecuritySection } from '../components/settings/AccountSecuritySection'
import { passwordStrength } from '../lib/password-strength'
import { useAuthStore } from '../store/auth'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderSecurity(routes: Array<{ method: string; suffix: string; respond: () => Response }>) {
  const fetchMock = vi.fn().mockImplementation((url: string | URL, init?: RequestInit) => {
    const target = String(url)
    const method = (init?.method ?? 'GET').toUpperCase()
    const route = routes.find((r) => r.method === method && target.endsWith(r.suffix))
    if (route) return Promise.resolve(route.respond())
    if (target.endsWith('/auth/sessions')) return Promise.resolve(jsonResponse([]))
    if (target.endsWith('/auth/login-events')) return Promise.resolve(jsonResponse({ items: [] }))
    if (target.endsWith('/auth/passkeys')) return Promise.resolve(jsonResponse([]))
    if (target.endsWith('/auth/totp'))
      return Promise.resolve(jsonResponse({ enabled: false, recoveryCodesRemaining: 0 }))
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
})

describe('N005 密码强度（本地评估）', () => {
  it('scorer 类别：弱 / 中 / 强与惩罚项', () => {
    expect(passwordStrength('')).toBeNull()
    // 弱：单一类别（长度换不回多样性）
    expect(passwordStrength('abcdefgh')).toBe('weak')
    expect(passwordStrength('12345678')).toBe('weak')
    expect(passwordStrength('abcdefghij')).toBe('weak')
    // 中：两类但长度一般 / 单一类别超长
    expect(passwordStrength('abc12345')).toBe('medium')
    expect(passwordStrength('abcdefghijklmnop')).toBe('medium')
    expect(passwordStrength('Abcdefg1')).toBe('medium')
    // 强：两类以上 + 长度 ≥12，且无连击/长序列
    expect(passwordStrength('Zx9!vT2q#Lm4')).toBe('strong')
    expect(passwordStrength('Ab1!x7Qm#9pT')).toBe('strong')
    // N005 惩罚：连击（aaa）与连续序列（bcdefghij）把强拉回中
    expect(passwordStrength('Abcaaaaaa123!')).toBe('medium')
    expect(passwordStrength('Abcdefghij12')).toBe('medium')
  })

  it('改密表单随输入渲染强度条；强度评估不发任何网络请求', async () => {
    const fetchMock = renderSecurity([])
    const input = await screen.findByLabelText('新密码')
    // 断言基线：初始读面已完成（会话/totp/会话列表/login-events）
    const baseline = fetchMock.mock.calls.length
    expect(baseline).toBeGreaterThan(0)

    fireEvent.change(input, { target: { value: 'abcdefgh' } })
    let meter = screen.getByTestId('password-strength')
    expect(meter.getAttribute('data-strength')).toBe('weak')
    expect(screen.getByText(/密码强度：弱/)).toBeInTheDocument()

    fireEvent.change(input, { target: { value: 'Zx9!vT2q#Lm4' } })
    meter = screen.getByTestId('password-strength')
    expect(meter.getAttribute('data-strength')).toBe('strong')
    expect(screen.getByText(/密码强度：强/)).toBeInTheDocument()

    fireEvent.change(input, { target: { value: '' } })
    expect(screen.queryByTestId('password-strength')).toBeNull()

    // 强度评估是纯本地的：整个交互过程没有新增任何 fetch 调用。
    expect(fetchMock.mock.calls.length).toBe(baseline)
  })
})

describe('N008 最近登录（新设备提醒）', () => {
  const events = [
    { id: 2, kind: 'new_device', deviceLabel: 'Firefox/Windows', createdAt: 1789900000, seen: false },
    { id: 1, kind: 'login', deviceLabel: 'Chrome/Linux', createdAt: 1789800000, seen: true },
  ]

  it('列出事件并渲染新设备徽标；标记已读走批量端点后徽标消失', async () => {
    let seen = false
    const fetchMock = renderSecurity([
      {
        method: 'GET',
        suffix: '/auth/login-events',
        respond: () =>
          jsonResponse({
            items: events.map((e) => (e.id === 2 ? { ...e, seen } : e)),
          }),
      },
      {
        method: 'POST',
        suffix: '/auth/login-events/seen',
        respond: () => {
          seen = true
          return jsonResponse({ marked: 1 })
        },
      },
    ])
    expect(await screen.findByText('最近登录（2）')).toBeInTheDocument()
    expect(screen.getByText('Chrome/Linux')).toBeInTheDocument()
    const badge = await screen.findByText('新设备')
    expect(badge).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /标记已读（1）/ }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([, init]) => (init?.method ?? '') === 'POST')).toBe(true)
    })
    await waitFor(() => {
      expect(screen.queryByText('新设备')).toBeNull()
    })
    // 批量端点收到空 body（= 全部未读）
    const seenCall = fetchMock.mock.calls.find(
      ([, init]) => (init?.method ?? '') === 'POST' && String(init?.body ?? '').includes('ids') === false,
    )
    expect(seenCall).toBeTruthy()
  })

  it('无事件时面板不渲染（诚实空态）', async () => {
    renderSecurity([])
    await screen.findByRole('button', { name: '更新密码' })
    expect(screen.queryByText(/最近登录（/)).toBeNull()
  })

  it('会话列表展示设备标签（deviceLabel 优先）', async () => {
    renderSecurity([
      {
        method: 'GET',
        suffix: '/auth/sessions',
        respond: () =>
          jsonResponse([
            {
              id: 'abcd1234',
              createdAt: 1789800000,
              lastSeenAt: 1789800000,
              expiresAt: 1999999999,
              userAgent: 'Mozilla/5.0 (X11; Linux x86_64) Chrome/126.0',
              deviceLabel: 'Chrome/Linux',
              current: true,
            },
          ]),
      },
    ])
    expect(await screen.findByText('Chrome/Linux')).toBeInTheDocument()
  })
})
