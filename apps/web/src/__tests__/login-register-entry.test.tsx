/** R01 登录面产品化 — 注册入口两态 + 错误位置测试。
 *
 * 真实组件 + mocked fetch：注册入口点击时懒探测
 * GET /auth/registration-policy（公开布尔策略位）——
 * - 开放 → 程序化导航进 /register；
 * - 关闭 → 就地展开邀请制说明 + 粘贴邀请码/链接进 /activate?token=；
 * - 端点不可用（404）→ 不猜测，回退 /register（服务端提交时定案）。
 * 错误位置：凭据类错误贴密码字段旁（login-credential-error），
 * 限流等服务级错误在表单级区域（login-feedback），互不混放。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import LoginScreen from '../components/LoginScreen'
import { useAuthStore } from '../store/auth'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderLogin() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <LoginScreen />
    </QueryClientProvider>,
  )
}

function policyFetchMock(policyResponse: () => Response): ReturnType<typeof vi.fn> {
  return vi.fn().mockImplementation((url: string | URL) => {
    if (String(url).endsWith('/auth/registration-policy')) {
      return Promise.resolve(policyResponse())
    }
    return Promise.resolve(jsonResponse({ authenticated: false, mode: 'session' }))
  })
}

beforeEach(() => {
  useAuthStore.setState({ status: 'unauthenticated', mode: 'session', identity: null })
  localStorage.clear()
  // 程序化导航用 history API——每个用例从干净路径出发。
  window.history.replaceState(null, '', '/')
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('R01 注册入口两态（策略探测）', () => {
  it('策略开放 → 点击注册入口进入 /register', async () => {
    vi.stubGlobal('fetch', policyFetchMock(() => jsonResponse({ allowPublicRegistration: true })))
    renderLogin()
    fireEvent.click(screen.getByTestId('login-register-link'))
    await waitForPath('/register')
    expect(window.location.search).toBe('')
  })

  it('策略关闭 → 邀请制说明面板 + 粘贴邀请码/链接进 /activate?token=', async () => {
    vi.stubGlobal('fetch', policyFetchMock(() => jsonResponse({ allowPublicRegistration: false })))
    renderLogin()
    fireEvent.click(screen.getByTestId('login-register-link'))
    const panel = await screen.findByTestId('login-invite-panel')
    // 邀请制诚实说明（不冒充可注册）。
    expect(panel).toHaveTextContent('邀请制')
    expect(screen.queryByTestId('login-register-link')).not.toBeInTheDocument()

    // 粘贴完整邀请链接（含 token 参数）→ 点「激活」→ /activate?token=…
    const input = screen.getByTestId('login-invite-input')
    fireEvent.change(input, {
      target: { value: 'https://rss.example.com/activate?token=inv-abc123' },
    })
    fireEvent.click(screen.getByTestId('login-invite-activate'))
    await waitForPath('/activate')
    expect(new URLSearchParams(window.location.search).get('token')).toBe('inv-abc123')
  })

  it('策略关闭 → 粘贴裸邀请码 + Enter 键同样进激活流；「返回」可收回面板', async () => {
    vi.stubGlobal('fetch', policyFetchMock(() => jsonResponse({ allowPublicRegistration: false })))
    renderLogin()
    fireEvent.click(screen.getByTestId('login-register-link'))
    await screen.findByTestId('login-invite-panel')
    fireEvent.change(screen.getByTestId('login-invite-input'), {
      target: { value: 'inv-bare-token' },
    })
    fireEvent.keyDown(screen.getByTestId('login-invite-input'), { key: 'Enter' })
    await waitForPath('/activate')
    expect(new URLSearchParams(window.location.search).get('token')).toBe('inv-bare-token')
  })

  it('策略端点不可用（404）→ 不猜测，回退进 /register（服务端提交时定案）', async () => {
    vi.stubGlobal(
      'fetch',
      policyFetchMock(() =>
        jsonResponse({ error: { type: 'http_error', message: 'not found' } }, 404),
      ),
    )
    renderLogin()
    fireEvent.click(screen.getByTestId('login-register-link'))
    await waitForPath('/register')
    // 不出现邀请面板（未知 ≠ 关闭，不编造邀请制结论）。
    expect(screen.queryByTestId('login-invite-panel')).not.toBeInTheDocument()
  })
})

describe('R01 登录错误位置（字段旁 vs 表单级）', () => {
  function credentialsFetchMock(response: () => Response): ReturnType<typeof vi.fn> {
    return vi.fn().mockImplementation((url: string | URL) => {
      if (String(url).endsWith('/auth/login')) {
        return Promise.resolve(response())
      }
      return Promise.resolve(jsonResponse({ authenticated: false, mode: 'session' }))
    })
  }

  function fillAndSubmit() {
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'wrong-pass' } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))
  }

  it('凭据错误 → 贴在密码字段旁（login-credential-error），不进表单级区域', async () => {
    vi.stubGlobal(
      'fetch',
      credentialsFetchMock(() =>
        jsonResponse(
          { error: { type: 'invalid_credentials', message: 'Incorrect username or password.' } },
          401,
        ),
      ),
    )
    renderLogin()
    fillAndSubmit()
    const fieldError = await screen.findByTestId('login-credential-error')
    expect(fieldError).toHaveTextContent('用户名或密码不正确')
    expect(fieldError).not.toHaveTextContent('Incorrect')
    // 凭据错误不占表单级区域（一错一位，不重复渲染）。
    expect(screen.queryByTestId('login-feedback')).not.toBeInTheDocument()
    // aria 语义与密码框同位绑定。
    expect(screen.getByLabelText('密码').getAttribute('aria-describedby')).toBe(
      'login-credential-error',
    )
    expect(useAuthStore.getState().status).toBe('unauthenticated')
  })

  it('限流 → 表单级区域（login-feedback），不冒充凭据字段错误', async () => {
    vi.stubGlobal(
      'fetch',
      credentialsFetchMock(() =>
        jsonResponse({ error: { type: 'rate_limited', message: 'Too many attempts.' } }, 429),
      ),
    )
    renderLogin()
    fillAndSubmit()
    const formError = await screen.findByRole('alert')
    expect(formError).toHaveTextContent('尝试过于频繁')
    expect(screen.queryByTestId('login-credential-error')).not.toBeInTheDocument()
    expect(useAuthStore.getState().status).toBe('unauthenticated')
  })
})

/** 等待程序化导航落地（pushState 同步生效，轮询防时序脆弱）。 */
async function waitForPath(path: string): Promise<void> {
  await waitFor(() => {
    expect(window.location.pathname).toBe(path)
  })
}
