/**
 * FIX-074 / FIX-075 — 圆角层级与表面层级基线守卫（source-level 断言，
 * jsdom 无真实级联样式；风格同 fix-071-077-078-design-tokens）。
 *
 * FIX-074（统一圆角层级）：tokens.css 冻结了 xs→4xl+full 的九档圆角
 * 并标注各档用途；卡片/弹窗/抽屉按档取值——浮层容器（Dialog/Sheet/
 * Popover）用 xl/lg 档，胶囊档（full）只属于 pill/switch/dot/图标钮。
 * 不得把容器一律做成胶囊形。
 *
 * FIX-075（统一表面层级）：深浅主题各自定义可分辨的 page surface 与
 * elevated surface（浮层底色），浮层一律 surface-elevated + border +
 * shadow，深浅主题都有可辨边界。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const read = (rel: string): string => readFileSync(resolve(__dirname, '..', rel), 'utf-8')

const tokensCss = read('styles/tokens.css')
const themesCss = read('styles/themes.css')
const dialog = read('components/ui/Dialog.tsx')
const sheet = read('components/ui/Sheet.tsx')
const popover = read('components/ui/Popover.tsx')

describe('FIX-074: 圆角层级', () => {
  it('tokens.css 冻结 xs→4xl+full 九档圆角（逐档递增）', () => {
    const ladder = ['xs', 'sm', 'md', 'lg', 'xl', '2xl', '3xl', '4xl', 'full']
    const values = ladder.map((tier) => {
      const m = tokensCss.match(new RegExp(`--lumi-radius-${tier}:\\s*([0-9]+)px`))
      expect(m, `--lumi-radius-${tier} 应在 tokens.css 定义`).not.toBeNull()
      return Number(m![1])
    })
    for (let i = 1; i < values.length; i++) {
      expect(values[i]).toBeGreaterThan(values[i - 1]!)
    }
    expect(values[values.length - 1]).toBe(999) // 胶囊档
  })

  it('浮层容器（Dialog/Sheet/Popover）用 xl/lg 档，不使用胶囊档', () => {
    for (const [name, text] of [
      ['Dialog', dialog],
      ['Sheet', sheet],
      ['Popover', popover],
    ] as const) {
      expect(text, name).toMatch(/lumi-radius-(xl|lg)/)
      expect(text, `${name} 容器不得用胶囊圆角`).not.toContain(
        'rounded-[var(--lumi-radius-full)]',
      )
    }
  })
})

describe('FIX-075: 表面层级', () => {
  function themeVar(block: string, name: string): string {
    const m = block.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]+)`))
    expect(m, `${name} 应在主题块中定义`).not.toBeNull()
    return m![1]
  }

  it('浅色与深色主题的 surface 与 surface-elevated 都可分辨（浮层有边界底色）', () => {
    const light = themesCss.slice(themesCss.indexOf(':root {'), themesCss.indexOf("[data-theme='dark'] {"))
    const dark = themesCss.slice(themesCss.indexOf("[data-theme='dark'] {"))
    for (const [label, block] of [
      ['浅色', light],
      ['深色', dark],
    ] as const) {
      const surface = themeVar(block, '--lumi-surface')
      const elevated = themeVar(block, '--lumi-surface-elevated')
      expect(elevated, `${label} elevated 应不同于 page surface`).not.toBe(surface)
    }
  })

  it('浮层一律 surface-elevated + border + shadow（Dialog/Popover/Sheet）', () => {
    for (const [name, text] of [
      ['Dialog', dialog],
      ['Popover', popover],
    ] as const) {
      expect(text, name).toContain('bg-[var(--lumi-surface-elevated)]')
      expect(text, name).toContain('border-[var(--lumi-border)]')
    }
    expect(sheet).toContain('bg-[var(--lumi-surface-elevated)]')
    expect(sheet).toContain('shadow-[var(--lumi-shadow-dialog)]')
    expect(dialog).toMatch(/shadow-\[var\(--lumi-shadow/)
  })
})
