/** 邀请激活页（/activate）Web 测试 — 0067。
 *
 * 覆盖：三态（无效邀请诚实提示 / 正常表单 / 成功进入应用）、
 * freshrssReady=false 的「绑定待准备」说明（不是报错）、客户端
 * 校验（username 规则、密码长度、确认一致）、服务端错误映射
 * （invite_invalid / weak_password）。
 *
 * 统一 vi.mock('../api/client')（保留 ApiError 等真实导出）；
 * BFF 不参与测试。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import ActivateScreen from '../components/ActivateScreen'
import { useAuthStore } from '../store/auth'

const mocks = vi.hoisted(() => ({
  getActivationPreview: vi.fn(),
  activateWithInvite: vi.fn(),
  getAuthSession: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getActivationPreview: mocks.getActivationPreview,
    activateWithInvite: mocks.activateWithInvite,
    getAuthSession: mocks.getAuthSession,
  }
})

function setUrl(url: string): void {
  window.history.replaceState(null, '', url)
}

function renderActivate() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <ActivateScreen />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  setUrl('/')
  vi.clearAllMocks()
})

beforeEach(() => {
  useAuthStore.setState({ status: 'unauthenticated', mode: 'session', identity: null })
  localStorage.clear()
})

describe('邀请状态三态', () => {
  it('无效邀请 → 诚实单一提示，不区分原因', async () => {
    setUrl('/activate?token=inv_dead')
    mocks.getActivationPreview.mockResolvedValue({ valid: false, kind: null, freshrssReady: false })
    renderActivate()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('邀请链接无效或已过期')
    expect(mocks.getActivationPreview).toHaveBeenCalledWith('inv_dead')
  })

  it('无 token（如手输 /activate）→ 直接进入无效态，不发请求', async () => {
    setUrl('/activate')
    renderActivate()
    expect(await screen.findByRole('alert')).toHaveTextContent('邀请链接无效或已过期')
    expect(mocks.getActivationPreview).not.toHaveBeenCalled()
  })

  it('有效邀请 → 渲染表单；freshrssReady=true 不出现绑定提示', async () => {
    setUrl('/activate?token=inv_ok')
    mocks.getActivationPreview.mockResolvedValue({ valid: true, kind: 'signup', freshrssReady: true })
    renderActivate()
    expect(await screen.findByLabelText('用户名')).toBeInTheDocument()
    expect(screen.queryByTestId('binding-pending-note')).not.toBeInTheDocument()
  })

  it('freshrssReady=false → 显示「待运营者准备」说明文案而非报错', async () => {
    setUrl('/activate?token=inv_ok')
    mocks.getActivationPreview.mockResolvedValue({ valid: true, kind: 'signup', freshrssReady: false })
    renderActivate()
    const note = await screen.findByTestId('binding-pending-note')
    expect(note).toHaveTextContent('RSS 源绑定待运营者准备，稍后自动完成')
    expect(note).not.toHaveTextContent('失败')
  })

  it('预览请求网络失败 → 错误 + 重试', async () => {
    setUrl('/activate?token=inv_ok')
    mocks.getActivationPreview.mockRejectedValue(new TypeError('Failed to fetch'))
    renderActivate()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('网络不可用')
    mocks.getActivationPreview.mockResolvedValue({ valid: true, kind: 'signup', freshrssReady: true })
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByLabelText('用户名')).toBeInTheDocument()
  })
})

describe('表单校验与提交', () => {
  async function renderReadyForm(freshrssReady = true) {
    setUrl('/activate?token=inv_ok')
    mocks.getActivationPreview.mockResolvedValue({ valid: true, kind: 'signup', freshrssReady })
    renderActivate()
    await screen.findByLabelText('用户名')
  }

  it('客户端校验：非法用户名 / 短密码 / 确认不一致 → 不发激活请求', async () => {
    await renderReadyForm()
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'Bad Name!' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'short' } })
    fireEvent.change(screen.getByLabelText('确认密码'), { target: { value: 'short2' } })
    fireEvent.click(screen.getByRole('button', { name: '激活并进入' }))
    expect(await screen.findByText(/仅限小写字母、数字/)).toBeInTheDocument()
    expect(screen.getByText('密码至少 8 位。')).toBeInTheDocument()
    expect(screen.getByText('两次输入的密码不一致。')).toBeInTheDocument()
    expect(mocks.activateWithInvite).not.toHaveBeenCalled()
  })

  it('合法输入 → POST 激活，成功后身份就位、门翻 authenticated', async () => {
    await renderReadyForm()
    // vi.mock 层拿到的是 client 解析后的对象（非 Response）
    mocks.activateWithInvite.mockResolvedValue({ authenticated: true, mode: 'session' })
    mocks.getAuthSession.mockResolvedValue({
      authenticated: true,
      mode: 'session',
      userId: 'u9',
      username: 'bob',
      role: 'member',
    })
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'bob' } })
    fireEvent.change(screen.getByLabelText('显示名（可选）'), { target: { value: '阿 Bob' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'longenough1' } })
    fireEvent.change(screen.getByLabelText('确认密码'), { target: { value: 'longenough1' } })
    fireEvent.click(screen.getByRole('button', { name: '激活并进入' }))
    await waitFor(() => {
      expect(useAuthStore.getState().status).toBe('authenticated')
    })
    expect(mocks.activateWithInvite).toHaveBeenCalledWith({
      token: 'inv_ok',
      username: 'bob',
      password: 'longenough1',
      displayName: '阿 Bob',
    })
    expect(useAuthStore.getState().identity).toEqual({ userId: 'u9', username: 'bob', role: 'member' })
    // 成功后回到应用主路由（不留 /activate 在地址栏）
    expect(window.location.pathname).toBe('/')
  })

  it('服务端 invite_invalid（竞态下已被用）→ 落到无效态', async () => {
    await renderReadyForm()
    mocks.activateWithInvite.mockRejectedValue(
      new ApiError(400, 'invite_invalid', 'Invitation is invalid, expired or already used.'),
    )
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'bob' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'longenough1' } })
    fireEvent.change(screen.getByLabelText('确认密码'), { target: { value: 'longenough1' } })
    fireEvent.click(screen.getByRole('button', { name: '激活并进入' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('邀请链接无效或已过期')
  })

  it('服务端 weak_password → 表单内提示，可改后重试（token 未烧掉）', async () => {
    await renderReadyForm()
    mocks.activateWithInvite.mockRejectedValue(
      new ApiError(400, 'weak_password', 'Password must be at least 8 characters.'),
    )
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'bob' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'longenough1' } })
    fireEvent.change(screen.getByLabelText('确认密码'), { target: { value: 'longenough1' } })
    fireEvent.click(screen.getByRole('button', { name: '激活并进入' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Password must be at least 8 characters.')
    // 仍在表单态（未落到无效态）
    expect(screen.getByLabelText('用户名')).toBeInTheDocument()
  })
})
