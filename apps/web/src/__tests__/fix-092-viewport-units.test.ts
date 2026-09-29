/**
 * FIX-092 — 移动端地址栏收缩不得造成 100vh 溢出/空白。
 *
 * 审计结论（2026-09 R2 基线）：全库（tsx/ts/css，测试除外）零 `100vh`
 * 与 `*-screen` 视口类；应用壳 `App.tsx` 用 `h-dvh`，认证面用
 * `min-h-dvh`，浮层面板用 `NNdvh`——按当前浏览器能力取可靠视口高度。
 * 本守卫钉定「不得回归到 100vh」这一约束。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const srcRoot = resolve(__dirname, '..')

function walk(dir: string, ext: RegExp): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    const st = statSync(p)
    if (st.isDirectory()) {
      if (name === '__tests__' || name === 'generated') continue
      out.push(...walk(p, ext))
    } else if (ext.test(name)) {
      out.push(p)
    }
  }
  return out
}

describe('FIX-092: 视口高度一律用动态单位（dvh），禁用 100vh / *-screen', () => {
  it('src 内（含样式）零 100vh、零 h-/min-h-/max-h-screen 视口高度类', () => {
    const offenders: string[] = []
    const files = [
      ...walk(srcRoot, /\.(tsx|ts)$/),
      ...walk(resolve(srcRoot, 'styles'), /\.css$/),
    ]
    for (const file of files) {
      const text = readFileSync(file, 'utf-8')
      const rel = relative(srcRoot, file)
      // 只约束视口「高度」（FIX-092 是地址栏收缩导致的纵向溢出）；
      // w-screen 是宽度选择（Dialog 移动端全幅面板），不在此列。
      for (const m of text.matchAll(/100vh|h-screen|min-h-screen|max-h-screen/g)) {
        const line = text.slice(0, m.index).split('\n').length
        offenders.push(`${rel}:${line} ${m[0]}`)
      }
    }
    expect(offenders).toEqual([])
  })

  it('应用壳与认证面使用 dvh（行为锚点仍在）', () => {
    const app = readFileSync(resolve(srcRoot, 'App.tsx'), 'utf-8')
    expect(app).toContain('h-dvh')
    for (const name of ['LoginScreen', 'ActivateScreen', 'RegisterScreen']) {
      const text = readFileSync(resolve(srcRoot, `components/${name}.tsx`), 'utf-8')
      expect(text, name).toContain('min-h-dvh')
    }
  })
})
