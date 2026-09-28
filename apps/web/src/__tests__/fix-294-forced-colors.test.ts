/**
 * FIX-294 — forced-colors（高对比系统模式）下纯背景信号不可消失。
 *
 * 背景：Windows 高对比等场景启用 forced-colors: active 后，浏览器把
 * background-color 强制为 ButtonFace——靠背景色存在的视觉信号（状态点、
 * 进度条填充、Switch 轨道/拇指）全部隐没，只剩文字。lucide 图标走
 * stroke=currentColor（color 被强制映射为合法系统色）不受影响；受害的
 * 是「纯背景承载」的信号。
 *
 * 修复（系统色保底，Tailwind `forced-colors:` 变体，媒体查询内生效）：
 * - 选择/进行类信号（未读点、朗读指示、进度填充、Switch 开态）→
 *   `forced-colors:bg-[Highlight]`（与系统选中语义一致）；
 * - 健康/错误状态点 → `forced-colors:bg-[CanvasText]`（最大对比，
 *   语义中性）；Switch 关态轨道 ButtonBorder + 拇指 ButtonText。
 * - ui/PasswordStrengthMeter 的分档条同为纯背景，但条下有可见文字
 *   （aria-live 文案）承载同等信息 → 按「状态不只靠颜色」原则可接受，
 *   不在本次强改范围。
 *
 * 守卫：仓库内不得新增「tiny 纯背景圆点且无 forced-colors 回退、也无
 * 文字色兜底」的元素（jsdom 无法模拟 forced-colors，故为 source 断言）。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const srcRoot = resolve(__dirname, '../components')

function walk(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    const st = statSync(p)
    if (st.isDirectory()) {
      out.push(...walk(p))
    } else if (name.endsWith('.tsx')) {
      out.push(p)
    }
  }
  return out
}

describe('FIX-294 forced-colors 纯背景信号保底', () => {
  it('tiny 纯背景圆点必须带 forced-colors 回退（或本身有文字色兜底）', () => {
    const offenders: string[] = []
    for (const file of walk(srcRoot)) {
      const lines = readFileSync(file, 'utf8').split('\n')
      for (let i = 0; i < lines.length; i++) {
        const L = `${lines[i]}\n${lines[i + 1] ?? ''}\n${lines[i + 2] ?? ''}`
        if (!L.includes('rounded-full')) continue
        if (!/bg-\[var\(--lumi-/.test(L)) continue
        // 只约束 tiny 点状/细条信号（size-1~2.5 / h-1~2）
        if (!/size-(?:1|1\.5|2|2\.5)['"\s]|[hw]-(?:1|1\.5|2)['"\s]/.test(L)) continue
        if (L.includes('forced-colors:')) continue
        // 常量引用（其定义含 forced-colors 由下方锚点断言钉住）
        if (/STRENGTH_COLOR\[/.test(L)) continue
        // 有文字色（token/系统）的元素在 forced-colors 下仍可见，放行
        if (/text-\[var\(--lumi-|text-(?:black|white)\b/.test(L)) continue
        offenders.push(`${file}:${i + 1} :: ${L.replace(/\s+/g, ' ').trim().slice(0, 100)}`)
      }
    }
    expect(offenders).toEqual([])
  })

  it('RegisterScreen STRENGTH_COLOR 三档均带系统色回退（常量锚点）', () => {
    const src = readFileSync(resolve(srcRoot, 'RegisterScreen.tsx'), 'utf8')
    const map = src.match(/const STRENGTH_COLOR[^}]+}/)?.[0] ?? ''
    expect(map).toContain('forced-colors:bg-[CanvasText]')
    expect(map).toContain('forced-colors:bg-[Highlight]')
  })

  it('Switch 原语：轨道/拇指/开态均有系统色回退', () => {
    const src = readFileSync(resolve(srcRoot, 'ui/Switch.tsx'), 'utf8')
    expect(src).toContain('forced-colors:bg-[ButtonBorder]')
    expect(src).toContain('forced-colors:data-checked:bg-[Highlight]')
    expect(src).toContain('forced-colors:bg-[ButtonText]')
  })

  it('WorkspaceBoard 进度条填充有 Highlight 回退', () => {
    const src = readFileSync(resolve(srcRoot, 'WorkspaceBoard.tsx'), 'utf8')
    expect(src).toMatch(/bg-\[var\(--lumi-accent\)\] forced-colors:bg-\[Highlight\]/)
  })

  it('PasswordStrengthMeter 分档条旁保留可见文字（状态不只靠颜色）', () => {
    const src = readFileSync(resolve(srcRoot, 'ui/PasswordStrengthMeter.tsx'), 'utf8')
    expect(src).toMatch(/aria-live="polite"/)
    expect(src).toMatch(/\{STRENGTH_TEXT\[strength\]\}/)
  })
})
