/**
 * FIX-072 — 同等级按钮尺寸基线守卫（source-level 断言，风格同
 * fix-074-075-radius-surface-baseline）。
 *
 * 裁决：BASELINE_OK。按钮高度/内边距/圆角已由明确的变体系统统一：
 * - Button primitive：variant（primary/secondary/ghost/danger）× size
 *   （sm/md）二维语义变体；尺寸只来自 sizeClasses 映射——
 *   sm = min-h-8 + px-2.5 + gap-1.5，md = min-h-10 + px-3.5 + gap-2；
 *   同 size 同高同内边距（Record<Size,string> 映射按构造保证）；
 *   圆角不进 variant，统一在共享 base 串上（radius-md 阶梯档）。
 * - IconButton primitive：size 三档显式盒尺寸（sm=size-7 / md=size-8 /
 *   lg=size-11），touch 只用透明伪元素外扩 44×44 命中区（FIX-076），
 *   不混入视觉尺寸档。
 * - 消费侧 `min-h-11` 覆盖是 F01 移动端触控约定（44px 触控目标），
 *   不属于同等级按钮的视觉不一致，不在本守卫范围。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const read = (rel: string): string => readFileSync(resolve(__dirname, '..', rel), 'utf-8')

const button = read('components/ui/Button.tsx')
const iconButton = read('components/ui/IconButton.tsx')

/** 抽取 `const sizeClasses...= { ... }` 对象字面量块体（闭于行首 `}`）。 */
function sizeBlock(src: string): string {
  const start = src.indexOf('const sizeClasses')
  expect(start, 'sizeClasses 声明应存在').toBeGreaterThan(-1)
  const open = src.indexOf('{', start)
  const close = src.indexOf('\n}', open)
  return src.slice(open + 1, close)
}

describe('FIX-072: Button 尺寸变体系统', () => {
  it('size 是显式语义档：sm/md 两档，每档恰好一个高度、一个水平内边距', () => {
    const block = sizeBlock(button)
    const rows = block
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => /:\s*'/.test(l))
    expect(rows.map((r) => r.split(':')[0])).toEqual(['sm', 'md'])
    for (const row of rows) {
      const body = row.match(/'([^']*)'/)![1]!
      const heights = body.match(/min-h-\S+/g) ?? []
      expect(heights, `size 档应恰好一个高度：${row}`).toHaveLength(1)
      expect(body, `size 档应有显式水平内边距：${row}`).toMatch(/\bpx-\S+/)
      expect(body, `size 档应有显式 gap：${row}`).toMatch(/\bgap-\S+/)
    }
  })

  it('高度集合收敛在 {min-h-8, min-h-10}：同 size 同高由映射唯一来源保证', () => {
    const block = sizeBlock(button)
    const heights = [...block.matchAll(/min-h-(\S+)/g)].map((m) => m[1])
    expect(new Set(heights).size).toBe(heights.length) // 每档一个、不混用
    for (const h of heights) {
      expect(['8', '10'], `高度档 ${h} 不在冻结集合 {8,10}`).toContain(h)
    }
  })

  it('圆角不随 variant/size 漂移：统一在共享 base（radius-md 阶梯档）', () => {
    // base 串携带唯一圆角；variantClasses 与 sizeClasses 内不得再出现 rounded-*
    const baseStart = button.indexOf('const base')
    const baseBlock = button.slice(baseStart, button.indexOf('\n\n', baseStart))
    expect(baseBlock).toContain('rounded-[var(--lumi-radius-md)]')
    for (const section of ['const variantClasses', 'const sizeClasses']) {
      const start = button.indexOf(section)
      const block = button.slice(start, button.indexOf('\n}', start))
      expect(block, `${section} 不得自带圆角`).not.toMatch(/\brounded/)
    }
    // 四个 variant 共享同一 base：cx(base, variantClasses[variant], sizeClasses[size], …)
    expect(button).toContain('cx(base, variantClasses[variant], sizeClasses[size]')
  })
})

describe('FIX-072: IconButton 尺寸变体系统', () => {
  it('三档显式盒尺寸（sm 28 / md 32 / lg 44），每档唯一 size-*', () => {
    const block = sizeBlock(iconButton)
    const rows = block
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => /:\s*'/.test(l))
    expect(rows.map((r) => r.split(':')[0])).toEqual(['sm', 'md', 'lg'])
    expect(new Set(rows.map((r) => r.match(/size-\d+/)?.[0]))).toEqual(
      new Set(['size-7', 'size-8', 'size-11']),
    )
  })

  it('触控 44×44 走透明伪元素命中区（FIX-076），不放大视觉盒', () => {
    expect(iconButton).toContain('after:size-11') // 命中区 = 44px
    expect(iconButton).toMatch(/touch && touchHitArea/)
  })
})
