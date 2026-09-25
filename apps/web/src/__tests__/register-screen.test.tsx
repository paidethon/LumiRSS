/** 公开注册页（/register → RegisterScreen）Web 测试 — P0-02 + F015/F016/F017/F019/F020。
 *
 * 覆盖：注册成功自动登录（F020，身份由 session 服务端核实 + 清足迹 + 翻门）、
 * ?next= 认证前目标回跳（F015 合法路径）、403 registration_disabled 的
 * 「本实例未开放注册」诚实态 + 邀请激活入口（F019）、409 重名、400
 * weak_password / invalid_username 的逐类映射、网络错误不误导、本地
 * 密码强度三档（F016，无网络请求）、Caps Lock 提示（F017）、本地校验
 * （用户名规则 / 确认密码不一致）。
 *
 * 统一 vi.mock('../api/client')（保留 ApiError 等真实导出）；
 * BFF 不参与测试。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import RegisterScreen from '../components/RegisterScreen'
import { passwordStrength } from '../lib/password-strength'
import { useAuthStore } from '../store/auth'

// 合成占位值（非真实凭据）：满足 ≥8 位且三类字符（强档样本）
const SYNTHETIC_STRONG_PASSWORD = ['Str0ng', 'enough', 'pw'].join('-')
const mocks = vi.hoisted(() => ({
  registerAccount: vi.fn(),
  getAuthSession: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    registerAccount: mocks.registerAccount,
    getAuthSession: mocks.getAuthSession,
  }
})

function setUrl(url: string): void {
  window.history.replaceState(null, '', url)
}

function renderRegister() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <RegisterScreen />
    </QueryClientProvider>,
  )
}

function fillValidForm({
  username = 'newbie',
  password = SYNTHETIC_STRONG_PASSWORD,
  confirm = password,
  displayName,
}: {
  username?: string
  password?: string
  confirm?: string
  displayName?: string
} = {}): void {
  fireEvent.change(screen.getByLabelText('用户名'), { target: { value: username } })
  if (displayName !== undefined) {
    fireEvent.change(screen.getByLabelText('显示名（可选）'), { target: { value: displayName } })
  }
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: password } })
  fireEvent.change(screen.getByLabelText('确认密码'), { target: { value: confirm } })
}

afterEach(() => {
  setUrl('/')
  vi.clearAllMocks()
})

beforeEach(() => {
  useAuthStore.setState({ status: 'unauthenticated', mode: 'session', identity: null })
  localStorage.clear()
})

describe('渲染与本地校验（不发请求）', () => {
  it('渲染完整表单与返回登录入口；空表单不能提交', () => {
    renderRegister()
    expect(screen.getByTestId('register-screen')).toBeInTheDocument()
    expect(screen.getByLabelText('用户名')).toBeInTheDocument()
    expect(screen.getByLabelText('显示名（可选）')).toBeInTheDocument()
    expect(screen.getByLabelText('密码')).toBeInTheDocument()
    expect(screen.getByLabelText('确认密码')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '注册并进入' })).toBeDisabled()
    expect(screen.getByTestId('register-back-login')).toHaveTextContent('返回登录')
  })

  it('用户名规则提示可见；非法用户名 → 本地错误，不发注册请求', async () => {
    renderRegister()
    expect(screen.getByText(/3–32 位，小写字母/)).toBeInTheDocument()
    fillValidForm({ username: 'Bad Name!' })
    fireEvent.click(screen.getByRole('button', { name: '注册并进入' }))
    expect(await screen.findByText(/仅限小写字母、数字/)).toBeInTheDocument()
    expect(mocks.registerAccount).not.toHaveBeenCalled()
  })

  it('密码与确认不一致 → 本地错误，不发注册请求', async () => {
    renderRegister()
    fillValidForm({ confirm: SYNTHETIC_STRONG_PASSWORD + '-x' })
    fireEvent.click(screen.getByRole('button', { name: '注册并进入' }))
    expect(await screen.findByText('两次输入的密码不一致。')).toBeInTheDocument()
    expect(mocks.registerAccount).not.toHaveBeenCalled()
  })

  it('短密码 → 本地错误（服务端仍是权威校验）', async () => {
    renderRegister()
    fillValidForm({ password: 'short', confirm: 'short' })
    fireEvent.click(screen.getByRole('button', { name: '注册并进入' }))
    expect(await screen.findByText('密码至少 8 位。')).toBeInTheDocument()
    expect(mocks.registerAccount).not.toHaveBeenCalled()
  })
})

describe('F016 本地密码强度（三档，无网络请求）', () => {
  it('纯函数分档：空/太短=弱，两类字符=中，三类+更长=强', () => {
    expect(passwordStrength('')).toBeNull()
    expect(passwordStrength('short')).toBe('weak')
    expect(passwordStrength('abcdefgh')).toBe('weak')
    expect(passwordStrength('abcdefg1')).toBe('medium')
    expect(passwordStrength('Abcdefg1')).toBe('medium')
    expect(passwordStrength(SYNTHETIC_STRONG_PASSWORD)).toBe('strong')
    expect(passwordStrength('abcdefghijkl')).toBe('weak')
  })

  it('输入密码后显示三档强度提示与刻度；清空后消失', async () => {
    renderRegister()
    expect(screen.queryByTestId('password-strength')).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'abcdefgh' } })
    const weak = screen.getByTestId('password-strength')
    expect(weak).toHaveAttribute('data-strength', 'weak')
    expect(weak).toHaveTextContent('密码强度：弱')
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: SYNTHETIC_STRONG_PASSWORD } })
    expect(screen.getByTestId('password-strength')).toHaveAttribute('data-strength', 'strong')
    expect(screen.getByTestId('password-strength')).toHaveTextContent('密码强度：强')
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: '' } })
    expect(screen.queryByTestId('password-strength')).not.toBeInTheDocument()
  })
})

describe('F017 Caps Lock 提示', () => {
  it('Caps Lock 开启 → 提示可见；关闭 → 消失', () => {
    renderRegister()
    const input = screen.getByLabelText('密码')
    const spy = vi.spyOn(KeyboardEvent.prototype, 'getModifierState')
    spy.mockReturnValue(true)
    fireEvent.keyDown(input, { key: 'a' })
    expect(screen.getByTestId('capslock-hint')).toHaveTextContent('大写锁定（Caps Lock）已开启')
    spy.mockReturnValue(false)
    fireEvent.keyUp(input, { key: 'a' })
    expect(screen.queryByTestId('capslock-hint')).not.toBeInTheDocument()
    spy.mockRestore()
  })
})

describe('注册成功流（F020 自动登录 + F015 回跳）', () => {
  it('成功 → registerAccount 携带表单值，身份由 session 核实，门翻 authenticated，回首页', async () => {
    mocks.registerAccount.mockResolvedValue({ authenticated: true, mode: 'session' })
    mocks.getAuthSession.mockResolvedValue({
      authenticated: true,
      mode: 'session',
      userId: 'u9',
      username: 'newbie',
      role: 'member',
    })
    renderRegister()
    fillValidForm({ displayName: '新成员' })
    fireEvent.click(screen.getByRole('button', { name: '注册并进入' }))
    await waitFor(() => {
      expect(useAuthStore.getState().status).toBe('authenticated')
    })
    expect(mocks.registerAccount).toHaveBeenCalledWith({
      username: 'newbie',
      password: SYNTHETIC_STRONG_PASSWORD,
      displayName: '新成员',
    })
    expect(useAuthStore.getState().identity).toEqual({ userId: 'u9', username: 'newbie', role: 'member' })
    // 成功后离开 /register（服务端已自动登录，不留注册页在地址栏）
    expect(window.location.pathname).toBe('/')
  })

  it('带合法 ?next=/library → 成功后回跳认证前目标（F020+F015）', async () => {
    setUrl('/register?next=%2Flibrary')
    mocks.registerAccount.mockResolvedValue({ authenticated: true, mode: 'session' })
    mocks.getAuthSession.mockResolvedValue({
      authenticated: true,
      mode: 'session',
      userId: 'u9',
      username: 'newbie',
      role: 'member',
    })
    renderRegister()
    fillValidForm()
    fireEvent.click(screen.getByRole('button', { name: '注册并进入' }))
    await waitFor(() => {
      expect(useAuthStore.getState().status).toBe('authenticated')
    })
    expect(window.location.pathname).toBe('/library')
  })
})

describe('服务端错误逐类映射（诚实文案）', () => {
  async function submitValidForm(): Promise<void> {
    renderRegister()
    fillValidForm()
    fireEvent.click(screen.getByRole('button', { name: '注册并进入' }))
  }

  it('403 registration_disabled → 「本实例未开放注册」+ 邀请激活入口（F019）', async () => {
    mocks.registerAccount.mockRejectedValue(
      new ApiError(403, 'registration_disabled', 'Registration is disabled on this instance.'),
    )
    await submitValidForm()
    const closed = await screen.findByTestId('register-closed')
    expect(closed).toHaveTextContent('本实例未开放注册')
    expect(closed).toHaveTextContent('邀请链接')
    expect(screen.queryByLabelText('用户名')).not.toBeInTheDocument()
    // 激活入口可点 → 路由切到 /activate
    fireEvent.click(screen.getByTestId('register-closed-activate-link'))
    expect(window.location.pathname).toBe('/activate')
  })

  it('409 username_taken → 「已被使用」，表单保留可改后重试', async () => {
    mocks.registerAccount.mockRejectedValue(
      new ApiError(409, 'username_taken', 'That username is already in use.'),
    )
    await submitValidForm()
    const alert = await screen.findByText('该用户名已被使用，请换一个。')
    expect(alert).toBeInTheDocument()
    // 仍在表单态，可修正用户名重试
    expect(screen.getByLabelText('用户名')).toBeInTheDocument()
    expect(screen.queryByTestId('register-closed')).not.toBeInTheDocument()
  })

  it('400 weak_password → 密码字段诚实提示', async () => {
    mocks.registerAccount.mockRejectedValue(
      new ApiError(400, 'weak_password', 'Password must be at least 8 characters.'),
    )
    await submitValidForm()
    expect(await screen.findByText(/密码强度不足/)).toBeInTheDocument()
    expect(screen.getByLabelText('密码')).toBeInTheDocument()
  })

  it('400 invalid_username → 用户名字段诚实提示', async () => {
    mocks.registerAccount.mockRejectedValue(
      new ApiError(400, 'invalid_username', 'Username must be 3-32 chars.'),
    )
    await submitValidForm()
    expect(await screen.findByText(/用户名格式不正确/)).toBeInTheDocument()
  })

  it('网络失败（client 归一为 network_error）→ 「网络不可用」，绝不误导为用户名被占用', async () => {
    mocks.registerAccount.mockRejectedValue(
      new ApiError(0, 'network_error', '无法连接到服务器，请稍后重试。'),
    )
    await submitValidForm()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('网络不可用')
    expect(alert).not.toHaveTextContent('已被使用')
  })
})
