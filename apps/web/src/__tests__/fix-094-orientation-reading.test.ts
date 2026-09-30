/** FIX-094 — 横竖屏切换后阅读面板宽度与滚动位置不失真（结构守卫）。
 *
 * 裁决：BASELINE_OK。三道既有机制分别覆盖「宽度」与「位置」：
 * 1. 宽度：Reader 列在 App 壳是 flex-1 + min-w-0（无持久化像素宽），
 *    侧栏/列表宽是 clamp 过的固定 px 值——旋转只是视口宽变化，Reader
 *    宽度由 flexbox 从当前视口即时推导，无陈旧宽度可失真；
 * 2. 连续滚动位置：阅读位置存储是 fraction(ratio)+锚文本，恢复按当前
 *    几何换算（lib/reading-position，FIX-140 套件已钉 50% 恢复恒等）；
 * 3. 分页模式：ReaderPager 监听 window resize（横竖屏切换必然触发）
 *    重测分页布局，页码经锚点近似保持（keepAnchor）。
 *
 * 本守卫钉住 jsdom 可验证的部分：
 *   A. 分页几何纯函数在「横→竖」宽度变化后完全由当前宽度重推导
 *      （页数钳制 + 位移用新 stride——绝无旧宽度残留）；
 *   B. ReaderPager 源码确有 resize→keepAnchor 重测接线；
 *   C. App 壳 Reader 列确为 flex-1 + min-w-0（宽度即时推导）。
 * 真实横竖屏切换的视觉结果（列宽铺满、滚动落点无跳变）依赖真机渲染
 * 几何，jsdom 无法验证——需真机/浏览器视觉验证，此处如实标注。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  clampPage,
  computePagedLayout,
  pageOffset,
} from '../lib/reader-pagination'

const appSrc = resolve(__dirname, '../App.tsx')
const readerPagerSrc = resolve(__dirname, '../components/ReaderPager.tsx')

describe('FIX-094: 分页几何随当前视口重推导（纯函数）', () => {
  it('横屏→竖屏：页数/栏宽/位移全部来自新宽度，页码钳制到新页数', () => {
    // 横屏：宽 800、页边距 24 → stride 800，内容 scrollWidth 9600 → 12 页
    const landscape = computePagedLayout({
      viewportWidth: 800,
      pageMarginPx: 24,
      articleScrollWidth: 9600,
    })
    expect(landscape.stride).toBe(800)
    expect(landscape.pageCount).toBe(12)
    expect(pageOffset(11, landscape.stride)).toBe(8800)

    // 旋转为竖屏：宽 390 → stride 390；同一内容重排后 scrollWidth 变为
    // 3900（几何由内容流决定，此处按竖屏实测值输入）→ 10 页
    const portrait = computePagedLayout({
      viewportWidth: 390,
      pageMarginPx: 24,
      articleScrollWidth: 3900,
    })
    expect(portrait.stride).toBe(390)
    expect(portrait.pageCount).toBe(10)

    // 旋转前停在最后一页（11）：新布局下钳制到第 9 页，位移 = 9×390，
    // 绝不出现旧 stride/旧页码换算的越界位移
    const clamped = clampPage(11, portrait.pageCount)
    expect(clamped).toBe(9)
    expect(pageOffset(clamped, portrait.stride)).toBe(3510)
  })

  it('退化输入（旋转瞬间量到 0 宽）收敛 1 页，绝不 NaN', () => {
    const degenerate = computePagedLayout({
      viewportWidth: 0,
      pageMarginPx: 24,
      articleScrollWidth: 0,
    })
    expect(degenerate.pageCount).toBe(1)
    expect(degenerate.columnWidth).toBe(0)
    expect(Number.isFinite(pageOffset(3, degenerate.stride))).toBe(true)
  })
})

describe('FIX-094: 结构接线（源码契约）', () => {
  it('ReaderPager 监听 window resize 并以 keepAnchor 重测（位置近似保持）', () => {
    const code = readFileSync(readerPagerSrc, 'utf8')
    expect(code).toContain("window.addEventListener('resize', onResize)")
    expect(code).toContain('measure({ keepAnchor: true, resetToSaved: false })')
  })

  it('App 壳 Reader 列为 flex-1 + min-w-0（宽度由当前视口推导，无持久像素宽）', () => {
    const code = readFileSync(appSrc, 'utf8')
    expect(code).toContain('min-h-0 min-w-0 flex-1 bg-[var(--lumi-surface)]')
    // 侧栏/列表宽是 clamp 过的常量（px），Reader 不持有持久化像素宽
    expect(code).toMatch(/SIDEBAR_MIN = 220/)
    expect(code).toMatch(/TIMELINE_MIN = 360/)
  })
})
