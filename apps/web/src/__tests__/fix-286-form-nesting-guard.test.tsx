/** FIX-286 — 表单嵌套 / Enter 提交外层危险操作契约护栏。
 *
 * 契约（审计缺陷类：嵌套 form 的 submit 事件冒泡会让内层表单的
 * Enter 隐式提交落到外层危险操作上）：
 * 1. 全代码库不存在 <form> 嵌套 <form>（无效 HTML，静态扫描断言）；
 * 2. 真实渲染的表单内所有 <button> 都带显式 type（原生默认 submit，
 *    非提交按钮必须 type="button"）；破坏性按钮（退出所有设备）不在
 *    任何 form 内；
 * 3. 修改密码表单提交（Enter 隐式提交）只触发 changePassword，绝不
 *    触发 logoutEverywhere。
 *
 * 基线现状（BASELINE_OK 验证）：全库无嵌套 form（Button/IconButton
 * 原语默认 type="button"，危险按钮位于 Dialog footer、form 之外）。
 * 突变注入验证：把修改密码表单改成 form 套 form、外层 onSubmit 调
 * logoutEverywhere → 静态扫描与行为断言同时变红。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import AccountMenu from '../components/AccountMenu'
import LoginScreen from '../components/LoginScreen'
import { useAuthStore, type AuthIdentity } from '../store/auth'

const mocks = vi.hoisted(() => ({
  changePassword: vi.fn(),
  logoutCurrent: vi.fn(),
  logoutEverywhere: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    changePassword: mocks.changePassword,
    logoutCurrent: mocks.logoutCurrent,
    logoutEverywhere: mocks.logoutEverywhere,
  }
})

const MEMBER: AuthIdentity = { userId: 'u2', username: 'bob', role: 'member' }

function renderMenu() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <AccountMenu />
    </QueryClientProvider>,
  )
}

/** 递归收集 src 下的 .ts/.tsx 源码（排除测试自身）。 */
function collectSourceFiles(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) {
      if (name === '__tests__') continue
      out.push(...collectSourceFiles(full))
    } else if ((name.endsWith('.ts') || name.endsWith('.tsx')) && !name.includes('.test.')) {
      out.push(full)
    }
  }
  return out
}

/** 深度扫描：返回嵌套（外层 form 未闭合又出现新 <form）的文件与行号。 */
function nestedFormSites(text: string): number[] {
  const sites: number[] = []
  let depth = 0
  for (const m of text.matchAll(/<(\/?)form\b/g)) {
    if (m[1] === '') {
      depth += 1
      if (depth >= 2) sites.push(text.slice(0, m.index ?? 0).split('\n').length)
    } else {
      depth = Math.max(0, depth - 1)
    }
  }
  return sites
}

async function openChangePasswordDialog() {
  renderMenu()
  fireEvent.click(screen.getByTestId('account-menu-trigger'))
  fireEvent.click(await screen.findByRole('menuitem', { name: '修改密码' }))
  await screen.findByLabelText('当前密码')
}

async function openLogoutAllDialog() {
  renderMenu()
  fireEvent.click(screen.getByTestId('account-menu-trigger'))
  fireEvent.click(await screen.findByRole('menuitem', { name: '退出所有设备' }))
  await screen.findByRole('dialog')
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  useAuthStore.setState({ status: 'unauthenticated', mode: 'session', identity: null })
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(() => new Response(JSON.stringify({}), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })),
  )
  vi.clearAllMocks()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('FIX-286 表单嵌套与非提交按钮契约', () => {
  it('静态扫描：全库源码不存在嵌套 <form>', () => {
    const srcDir = join(process.cwd(), 'src')
    const offenders = collectSourceFiles(srcDir)
      .map((file) => ({ file, sites: nestedFormSites(readFileSync(file, 'utf8')) }))
      .filter((entry) => entry.sites.length > 0)
    expect(offenders).toEqual([])
  })

  it('AccountMenu 两个弹层：无 form 嵌套；危险按钮不在任何 form 内且 type="button"', async () => {
    useAuthStore.setState({ status: 'authenticated', mode: 'session', identity: MEMBER })
    // 修改密码弹层：change-password form 是唯一表单（提交按钮在 Dialog footer）
    const password = render(
      <QueryClientProvider client={new QueryClient()}>
        <AccountMenu />
      </QueryClientProvider>,
    )
    fireEvent.click(screen.getByTestId('account-menu-trigger'))
    fireEvent.click(await screen.findByRole('menuitem', { name: '修改密码' }))
    await screen.findByLabelText('当前密码')

    // Dialog 内容经 portal 挂在 body 下——必须查 document.body 才有效
    expect(document.body.querySelectorAll('form').length).toBeGreaterThanOrEqual(1)
    expect(document.body.querySelector('form form')).toBeNull()
    password.unmount()

    // 退出所有设备弹层：破坏性按钮必须在 form 之外（无意外提交路径）
    await openLogoutAllDialog()
    const danger = screen.getByRole('button', { name: '退出所有设备' })
    expect(danger.closest('form')).toBeNull()
    expect(danger.getAttribute('type')).toBe('button')
  })

  it('LoginScreen 登录表单：form 内所有 <button> 均带显式 type（原生默认 submit）', () => {
    const login = render(
      <QueryClientProvider client={new QueryClient()}>
        <LoginScreen />
      </QueryClientProvider>,
    )
    const inFormButtons = Array.from(login.container.querySelectorAll('form button'))
    // 登录表单内含「注册新账号 / 前往激活」等非提交按钮——契约要求显式 type
    expect(inFormButtons.length).toBeGreaterThanOrEqual(2)
    for (const button of inFormButtons) {
      expect(button.getAttribute('type'), 'form 内按钮缺显式 type').not.toBeNull()
    }
  })

  it('修改密码表单 submit（Enter 隐式提交）→ 只调 changePassword，不触发 logoutEverywhere', async () => {
    useAuthStore.setState({ status: 'authenticated', mode: 'session', identity: MEMBER })
    mocks.changePassword.mockResolvedValue({ authenticated: true, mode: 'session' })
    await openChangePasswordDialog()
    fireEvent.change(screen.getByLabelText('当前密码'), { target: { value: 'old-secret-1' } })
    fireEvent.change(screen.getByLabelText('新密码'), { target: { value: 'new-secret-1' } })
    // Enter 隐式提交等价于对所在 form 派发 submit；若存在外层嵌套 form，
    // submit 冒泡会让外层危险 onSubmit 一并执行——此处必须只有一次提交。
    fireEvent.submit(screen.getByLabelText('当前密码').closest('form')!)
    await waitFor(() => {
      expect(mocks.changePassword).toHaveBeenCalledTimes(1)
    })
    expect(mocks.changePassword).toHaveBeenCalledWith('old-secret-1', 'new-secret-1')
    expect(mocks.logoutEverywhere).not.toHaveBeenCalled()
    expect(mocks.logoutCurrent).not.toHaveBeenCalled()
  })
})
