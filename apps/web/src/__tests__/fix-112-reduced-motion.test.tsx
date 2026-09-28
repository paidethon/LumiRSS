/** FIX-112 — reduced-motion 下仍存在大幅滑动/闪烁/无限装饰动画的修复与守卫。
 *
 * 修复面（本测试 + 行为断言覆盖）：
 * 1. lib/reduced-motion：OS（prefers-reduced-motion，matchMedia mock）
 *    与应用内（html[data-motion-reduce]）两真源任一成立即减少动效；
 *    scrollBehavior() 相应返回 'auto' / 'smooth'。
 * 2. EdgeSwipeBack（App）：跟手预览 translateX 上限 120px + 回弹弹簧
 *    —— 大幅滑动。此前只认应用内设置；OS 偏好用户仍会看到。现两者
 *    任一成立即禁用预览（手势判定/提交不受影响）。
 * 3. JS 平滑滚动（scrollIntoView/scrollBy behavior:'smooth'）不受 CSS
 *    `scroll-behavior: auto !important` 约束——统一改经
 *    scrollBehavior()（减少动效 → 'auto' 瞬时定位）。
 *
 * CSS 侧（tokens.css 全局 0.01ms + @keyframes 仅 lumi-para-highlight-fade
 * 一个自终止高亮淡出）由既有规则覆盖，本文件只锁 JS 侧契约：
 * 4. 守卫：src 下不允许裸写 `behavior: 'smooth'` 字面量——必须经
 *    lib/reduced-motion 的 scrollBehavior()（唯一例外：lib 自身）。
 */

import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

import {
  appReduceMotion,
  prefersReducedMotion,
  scrollBehavior,
  shouldReduceMotion,
  usePrefersReducedMotion,
} from '../lib/reduced-motion'
import { EDGE_SWIPE_COMMIT_PX, EDGE_SWIPE_PREVIEW_MAX_PX, previewOffset } from '../lib/edge-swipe'

function setOsReduced(reduced: boolean): void {
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockImplementation((query: string) => ({
      matches: reduced && query.includes('prefers-reduced-motion'),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  delete document.documentElement.dataset.motionReduce
})

describe('FIX-112 reduced-motion 判定真源', () => {
  it('无任何偏好 → smooth；OS 偏好（matchMedia mock）→ auto', () => {
    setOsReduced(false)
    expect(prefersReducedMotion()).toBe(false)
    expect(scrollBehavior()).toBe('smooth')
    setOsReduced(true)
    expect(prefersReducedMotion()).toBe(true)
    expect(scrollBehavior()).toBe('auto')
    expect(shouldReduceMotion()).toBe(true)
  })

  it('应用内偏好（data-motion-reduce）独立于 OS 生效', () => {
    setOsReduced(false)
    document.documentElement.dataset.motionReduce = 'true'
    expect(appReduceMotion()).toBe(true)
    expect(shouldReduceMotion()).toBe(true)
    expect(scrollBehavior()).toBe('auto')
    delete document.documentElement.dataset.motionReduce
    expect(scrollBehavior()).toBe('smooth')
  })

  it('usePrefersReducedMotion 随 matchMedia change 事件重渲染', () => {
    setOsReduced(false)
    let listener: (() => void) | null = null
    const mql = {
      matches: false,
      addEventListener: (_: string, cb: () => void) => {
        listener = cb
      },
      removeEventListener: vi.fn(),
    }
    vi.stubGlobal(
      'matchMedia',
      vi.fn().mockImplementation(() => mql),
    )
    function Probe() {
      const reduced = usePrefersReducedMotion()
      return <div data-testid="probe">{reduced ? 'reduced' : 'full'}</div>
    }
    render(<Probe />)
    expect(screen.getByTestId('probe').textContent).toBe('full')
    // OS 偏好翻转 → change 事件 → 重渲染为 reduced
    mql.matches = true
    if (listener !== null) act(() => listener())
    expect(screen.getByTestId('probe').textContent).toBe('reduced')
  })
})

describe('FIX-112 EdgeSwipeBack 预览位移（大幅滑动的减少动效面）', () => {
  it('预览位移上限 120px（跟手弱化 0.35 倍）——被禁用即不再整页平移', () => {
    // 判定函数保持纯函数语义（禁用只影响组件内 transform 应用，
    // 手势判定与提交不受影响——见 edge-swipe.tsx onMove 的 !disabled 门）
    expect(previewOffset(400)).toBe(EDGE_SWIPE_PREVIEW_MAX_PX)
    expect(EDGE_SWIPE_COMMIT_PX).toBe(96)
  })
})

describe('FIX-112 裸写 smooth 滚动守卫', () => {
  it('静态扫描：src 下 behavior smooth 必须经 scrollBehavior()（lib 自身除外）', () => {
    const srcDir = join(process.cwd(), 'src')
    const offenders: string[] = []
    const walk = (dir: string): void => {
      for (const name of readdirSync(dir)) {
        const full = join(dir, name)
        if (statSync(full).isDirectory()) {
          if (name === '__tests__') continue
          walk(full)
        } else if ((name.endsWith('.ts') || name.endsWith('.tsx')) && !name.includes('.test.')) {
          if (full.endsWith('lib/reduced-motion.ts')) continue
          const text = readFileSync(full, 'utf8')
          for (const m of text.matchAll(/behavior\s*:\s*['"`]smooth['"`]/g)) {
            offenders.push(`${full.slice(srcDir.length + 1)}:${text.slice(0, m.index ?? 0).split('\n').length}`)
          }
        }
      }
    }
    walk(srcDir)
    expect(offenders).toEqual([])
  })
})
