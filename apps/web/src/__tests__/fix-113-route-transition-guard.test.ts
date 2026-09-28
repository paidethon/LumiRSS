/** FIX-113 — 页面切换动画核验：无点击阻塞层、无上一账户内容闪现。
 *
 * BASELINE_OK 核验（诚实证据）：Lumi 路由切换（section 切换 + 懒加载
 * 一级页）**不存在**路由过渡动画层——
 * 1. 无 framer-motion / motion/react / react-transition-group /
 *    AnimatePresence / CSSTransition 依赖或 import；
 * 2. RouteBoundary = RouteErrorBoundary + Suspense（fallback 骨架**替换**
 *    内容原位渲染，不是覆盖层）——导航完成后没有残留的拦截点击的
 *    fixed/inert 遮罩；route shell 不携带动画类；
 * 3. 上一账户内容：换账号走 lib/auth-reset.resetAccountState 单一入口
 *    （queryClient.clear() + UI 状态重置 + 本机足迹清理 + auth epoch
 *    广播），行为契约由 auth-reset.test.ts / auth-session.test.tsx /
 *    use-auth-gate 相关套件覆盖——本文件只锁「无过渡动画层」的静态
 *    契约，防止未来引入会遮挡点击或跨账号淡入旧画面的路由过渡。
 *
 * 突变注入验证：在 App 引入 AnimatePresence 包裹路由 → 守卫变红。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const APP_SRC = readFileSync(join(process.cwd(), 'src/App.tsx'), 'utf8')
const PKG = JSON.parse(readFileSync(join(process.cwd(), 'package.json'), 'utf8')) as {
  dependencies?: Record<string, string>
  devDependencies?: Record<string, string>
}

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

describe('FIX-113 路由无过渡动画层（BASELINE_OK 守卫）', () => {
  it('依赖里没有路由过渡动画库', () => {
    const deps = { ...PKG.dependencies, ...PKG.devDependencies }
    const banned = Object.keys(deps).filter((name) =>
      ['framer-motion', 'motion', 'react-transition-group', '@react-spring/web', 'react-overdrive'].includes(name),
    )
    expect(banned).toEqual([])
  })

  it('src 内无 AnimatePresence / CSSTransition / react-transition-group import', () => {
    const srcDir = join(process.cwd(), 'src')
    const offenders = collectSourceFiles(srcDir)
      .map((file) => {
        const text = readFileSync(file, 'utf8')
        return /AnimatePresence|CSSTransition|react-transition-group|from ['"]motion\/react['"]/.test(text)
          ? file.slice(srcDir.length + 1)
          : null
      })
      .filter((v): v is string => v !== null)
    expect(offenders).toEqual([])
  })

  it('RouteBoundary 是原位替换（error boundary + Suspense），不携带动画/遮罩类', () => {
    const start = APP_SRC.indexOf('function RouteBoundary')
    expect(start).toBeGreaterThan(0)
    const fn = APP_SRC.slice(start, APP_SRC.indexOf('}', APP_SRC.indexOf('</RouteErrorBoundary>', start)) + 1)
    expect(fn).toContain('RouteErrorBoundary')
    expect(fn).toContain('Suspense')
    // 无动画类、无覆盖层类（fixed/inset-0/pointer-events 出现在过渡层
    // 就会阻塞切换后的点击——route shell 一律不得有）
    expect(fn).not.toMatch(/\banimate-|transition-|pointer-events-|fixed |inset-0/)
  })
})
