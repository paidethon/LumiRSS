/**
 * FIX-091 / FIX-097 — 响应式基线守卫（source-level 断言）。
 *
 * FIX-091（安全区）：viewport-fit=cover + index.css 集中定义四向
 * --safe-* env 别名；底部导航岛经 var(--safe-bottom) 计入
 * Home indicator（运行时行为另有 fix-099-bottom-inset-clearance
 * 守卫，本文件钉住定义与接线不被删）。
 *
 * FIX-097（三栏最小宽度）：侧栏与文章列表宽度由常量 clamp
 * （SIDEBAR 220–300 / TIMELINE 360–460）经 PaneSeparator 调整；
 * 列本身 shrink-0 / flex-none + basis——缩窗时列宽不互相挤压，
 * 只在 clamp 区间内变化。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const read = (rel: string): string => readFileSync(resolve(__dirname, '..', rel), 'utf-8')

const indexHtml = read('../index.html')
const indexCss = read('index.css')
const app = read('App.tsx')
const paneSeparator = read('components/ui/PaneSeparator.tsx')
const mobileTabBar = read('components/MobileTabBar.tsx')

describe('FIX-091: iPhone 安全区', () => {
  it('viewport-fit=cover + index.css 集中定义四向 --safe-* env 别名', () => {
    expect(indexHtml).toMatch(/viewport-fit=cover/)
    for (const side of ['top', 'right', 'bottom', 'left']) {
      expect(
        indexCss,
        `--safe-${side} 应在 index.css 集中定义`,
      ).toMatch(new RegExp(`--safe-${side}:\\s*env\\(safe-area-inset-${side}`))
    }
  })

  it('底部导航岛 paddingBottom 计入 var(--safe-bottom)（不与 Home indicator 重叠）', () => {
    expect(mobileTabBar).toMatch(/var\(--safe-bottom\)/)
  })
})

describe('FIX-097: 桌面三栏最小宽度与拖动边界', () => {
  it('宽度常量 clamp 区间成立：SIDEBAR 220–300，TIMELINE 360–460', () => {
    expect(app).toMatch(/const SIDEBAR_MIN = 220/)
    expect(app).toMatch(/const SIDEBAR_MAX = 300/)
    expect(app).toMatch(/const TIMELINE_MIN = 360/)
    expect(app).toMatch(/const TIMELINE_MAX = 460/)
  })

  it('两个分隔条都把 min/max 常量交给 PaneSeparator（统一 clamp）', () => {
    // 侧栏分隔条
    expect(app).toMatch(/label="侧栏宽度"[\s\S]{0,120}min=\{SIDEBAR_MIN\}[\s\S]{0,40}max=\{SIDEBAR_MAX\}/)
    // 文章列表分隔条
    expect(app).toMatch(/label="文章列表宽度"[\s\S]{0,120}min=\{TIMELINE_MIN\}[\s\S]{0,40}max=\{TIMELINE_MAX\}/)
    expect(paneSeparator).toMatch(/onChange\(clamp\(/)
  })

  it('列不互相挤压：desktop 列位 flex-none + basis 变量，分隔条 shrink-0', () => {
    // desktop Timeline 列：CSS 变量 basis + 不参与挤压
    expect(app).toMatch(/lg:flex-none lg:basis-\[var\(--lumi-timeline-width\)\]/)
    // tablet 横排双栏同样定宽
    expect(app).toMatch(/w-auto shrink-0 grow-0 basis-\[var\(--lumi-timeline-width\)\]/)
    // aside 宽度走持久化设置 + shrink-0
    expect(app).toMatch(/shrink-0 overflow-y-auto bg-\[var\(--lumi-sidebar\)\]/)
    expect(paneSeparator).toMatch(/shrink-0/)
  })
})
