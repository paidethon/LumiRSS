/**
 * FIX-011 / 013 / 014 / 015 / 016 / 019 / 020 — 登录与激活表单语义守卫。
 *
 * 审计结论（2026-09 R2）：三个认证面（Login / Activate / Register）的
 * 语义基线已全部就位，本文件把它们钉成契约，防回归：
 * - FIX-011：autocomplete 语义齐备（username / current-password /
 *   new-password / nickname / one-time-code）——密码管理器自动填充
 *   能按字段语义命中；
 * - FIX-013：提交在途（pending）时重复点击/回车只发一次请求；
 * - FIX-014：密码显隐按钮 type="button" + onMouseDown preventDefault
 *   （不夺焦点、不误提交）+ aria-pressed；
 * - FIX-015：登录失败保留用户名与密码输入，错误走 role=alert 统一
 *   文案，不回显服务端细节；
 * - FIX-016：前后端都不 trim 密码（loginAccount(username.trim(),
 *   password)；BFF auth_store 无 trim），激活/注册最小密码长度前后端
 *   同为 8；
 * - FIX-019：认证面 input 一律 text-base（16px）——iOS 聚焦不触发
 *   自动放大；控件 min-h-11 满足 44px 命中区；
 * - FIX-020：认证面根容器 min-h-dvh + 不透明 var(--lumi-canvas)
 *   （浅/深主题都不透出底层阅读界面）+ 安全区内边距。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import LoginScreen from '../components/LoginScreen'
import { useAuthStore } from '../store/auth'

const srcRoot = resolve(__dirname, '..')

const loginSource = readFileSync(resolve(srcRoot, 'components/LoginScreen.tsx'), 'utf-8')
const activateSource = readFileSync(resolve(srcRoot, 'components/ActivateScreen.tsx'), 'utf-8')
const registerSource = readFileSync(resolve(srcRoot, 'components/RegisterScreen.tsx'), 'utf-8')
// 前后端契约同源（monorepo）：BFF 的最小密码长度与不 trim 语义。
const bffAuthStore = readFileSync(
  resolve(srcRoot, '../../../services/bff/src/lumirss/auth_store.py'),
  'utf-8',
)

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

/** 永不 resolve 的登录响应（验证在途守卫用）。 */
function makeDeferredLogin() {
  let resolve!: (r: Response) => void
  const promise = new Promise<Response>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

beforeEach(() => {
  useAuthStore.setState({ status: 'unauthenticated', mode: 'session', identity: null })
  localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('FIX-011: 密码管理器 autocomplete 语义', () => {
  it('登录面：username / current-password（渲染级断言）', () => {
    renderLogin()
    expect(screen.getByLabelText('用户名').getAttribute('autoComplete')).toBe('username')
    expect(screen.getByLabelText('密码').getAttribute('autoComplete')).toBe('current-password')
  })

  it('激活/注册面：new-password + nickname；TOTP 步 one-time-code（源码级断言）', () => {
    for (const source of [activateSource, registerSource]) {
      expect(source).toContain('autoComplete="username"')
      expect(source).toContain('autoComplete="new-password"')
      expect(source).toContain('autoComplete="nickname"')
    }
    expect(loginSource).toContain('autoComplete="one-time-code"')
  })
})

describe('FIX-013: 提交在途时重复点击只发一次请求', () => {
  it('pending 中再次点击登录 → fetch 仍只调用一次 /auth/login；失败后恢复可交互', async () => {
    const deferred = makeDeferredLogin()
    const fetchMock = vi.fn().mockImplementation((url: string | URL) => {
      if (String(url).endsWith('/auth/login')) return deferred.promise
      return Promise.resolve(jsonResponse({ authenticated: false }))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderLogin()
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'secret-1' } })

    const submit = screen.getByRole('button', { name: /登录/ })
    fireEvent.click(submit)
    await waitFor(() => expect(submit.hasAttribute('disabled')).toBe(true))
    fireEvent.click(submit)
    fireEvent.submit(submit.closest('form')!)
    expect(fetchMock.mock.calls.filter(([u]) => String(u).endsWith('/auth/login'))).toHaveLength(1)

    // 服务端拒绝 → 失败反馈出现、按钮恢复可交互（FIX-013 尾半句）。
    deferred.resolve(
      jsonResponse({ error: { type: 'invalid_credentials', message: 'Incorrect username or password.' } }, 401),
    )
    await screen.findByRole('alert')
    await waitFor(() => expect(submit.hasAttribute('disabled')).toBe(false))
  })
})

describe('FIX-014: 密码显隐按钮不夺焦点、不误提交', () => {
  it('三个认证面的显隐按钮：type=button + onMouseDown preventDefault + aria-pressed', () => {
    for (const [name, source] of [
      ['LoginScreen', loginSource],
      ['ActivateScreen', activateSource],
      ['RegisterScreen', registerSource],
    ] as const) {
      const buttonStart = source.indexOf("aria-label={reveal ? '隐藏密码' : '显示密码'}")
      expect(buttonStart, name).toBeGreaterThan(-1)
      // 按钮开标签：从 aria-label 往前找最近的 <button。
      const open = source.lastIndexOf('<button', buttonStart)
      const tag = source.slice(open, buttonStart + 200)
      expect(tag, name).toContain('type="button"')
      expect(tag, name).toContain('onMouseDown={(e) => e.preventDefault()}')
      expect(tag, name).toContain('aria-pressed={reveal}')
    }
  })

  it('点击显隐只切换输入类型，不触发表单提交', () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    renderLogin()
    const password = screen.getByLabelText('密码') as HTMLInputElement
    const reveal = screen.getByRole('button', { name: '显示密码' })
    expect(password.type).toBe('password')
    fireEvent.click(reveal)
    expect(password.type).toBe('text')
    expect(screen.getByRole('button', { name: '隐藏密码' })).toBeTruthy()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe('FIX-015: 登录失败保留输入、错误走 alert 且不回显服务端细节', () => {
  it('invalid_credentials → 统一文案；用户名与密码保留', async () => {
    const serverDetail = 'NoSuchUser: user alice (auth_backend.py:123)'
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string | URL) => {
        if (String(url).endsWith('/auth/login')) {
          return Promise.resolve(
            jsonResponse({ error: { type: 'invalid_credentials', message: serverDetail } }, 401),
          )
        }
        return Promise.resolve(jsonResponse({ authenticated: false }))
      }),
    )
    renderLogin()
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'wrong-pass' } })
    fireEvent.submit(screen.getByRole('button', { name: /登录/ }).closest('form')!)

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toBe('用户名或密码不正确。')
    expect(alert.textContent).not.toContain('auth_backend')
    expect((screen.getByLabelText('用户名') as HTMLInputElement).value).toBe('alice')
    expect((screen.getByLabelText('密码') as HTMLInputElement).value).toBe('wrong-pass')
  })
})

describe('FIX-016: 密码前后端都不 trim，最小长度一致', () => {
  it('web 提交路径只 trim 用户名，绝不 trim 密码', () => {
    expect(loginSource).toContain('loginAccount(username.trim(), password)')
    for (const [name, source] of [
      ['LoginScreen', loginSource],
      ['ActivateScreen', activateSource],
      ['RegisterScreen', registerSource],
    ] as const) {
      expect(source, name).not.toMatch(/password\.trim\(\)/)
      expect(source, name).not.toMatch(/confirm\.trim\(\)/)
    }
  })

  it('激活/注册最小密码长度 web=8 且与 BFF MIN_PASSWORD_LENGTH 同源一致', () => {
    expect(activateSource).toContain('MIN_PASSWORD_LENGTH = 8')
    expect(registerSource).toContain('MIN_PASSWORD_LENGTH = 8')
    expect(bffAuthStore).toContain('MIN_PASSWORD_LENGTH = 8')
    // BFF 认证存储从不 trim 密码（服务端语义同源钉定）。
    expect(bffAuthStore).not.toMatch(/password\.strip\(\)/)
  })
})

describe('FIX-019: 认证面 input 一律 text-base（iOS 不触发聚焦放大）', () => {
  it('三个认证面的每个 <input> className 都含 text-base，且无 text-sm/text-xs', () => {
    for (const [name, source] of [
      ['LoginScreen', loginSource],
      ['ActivateScreen', activateSource],
      ['RegisterScreen', registerSource],
    ] as const) {
      for (const m of source.matchAll(/<(input|Input)\b/g)) {
        // 输入标签范围：到第一个引号外 '>'（inputClassName 变量形式额外覆盖）。
        const tag = source.slice(m.index, source.indexOf('>', m.index) + 1)
        const cls = /className=\{?[`"']([^`"']+)/.exec(tag)?.[1] ?? ''
        if (cls === '') continue // inputClassName 常量形式在下方单独断言
        expect(cls, `${name} input @${source.slice(0, m.index).split('\n').length}`).toContain('text-base')
        expect(cls, name).not.toMatch(/text-(sm|xs)\b/)
      }
      // RegisterScreen 通过共享 inputClassName 常量供 16px。
      if (name === 'RegisterScreen') {
        expect(source).toMatch(/const inputClassName =[\s\S]*?text-base/)
      }
    }
  })
})

describe('FIX-020: 认证面根容器 = 不透明主题画布 + dvh + 安全区', () => {
  it('三个认证面根 div：min-h-dvh + bg-[var(--lumi-canvas)] + safe-area 内边距', () => {
    const rootPattern =
      /min-h-dvh items-center justify-center bg-\[var\(--lumi-canvas\)\][\s\S]*?safe-area-inset-top[\s\S]*?safe-area-inset-bottom/
    expect(loginSource).toMatch(rootPattern)
    expect(activateSource).toMatch(rootPattern)
    expect(registerSource).toMatch(rootPattern)
  })
})
