/** FIX-116 — 骨架屏与真实内容行高对齐（加载完成不大幅布局偏移）。
 *
 * 缺陷：时间线/稍后读 pending 骨架行高 ~34px（h-3+h-4+gap），真实
 * EntryCard 行 canonical 高 ~88px（.lumi-row-cv 的 contain-intrinsic-
 * size 即 88px）——首屏加载完成瞬间整个列表上跳 ~3 倍行差（CLS）。
 *
 * 契约（静态断言；jsdom 无布局引擎，真实像素由 min-h 保证）：
 * 1. EntryList 两处 pending 骨架行容器 min-h-[5.5rem]（88px）；
 * 2. App PageSkeleton 骨架行高 88px（h-[5.5rem]，原 h-16=64px 低估）；
 * 3. 88px 与 index.css `.lumi-row-cv` 的 contain-intrinsic-size 同源——
 *    两处若漂移即变红（行高估算的唯一真源）。
 *
 * 突变注入验证：把任一 min-h-[5.5rem]/h-[5.5rem] 改回原值 → 对应断言
 * 变红；把 contain-intrinsic-size 改成非 88px → 同源断言变红。
 */

import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const ENTRY_LIST_SRC = readFileSync(join(process.cwd(), 'src/components/EntryList.tsx'), 'utf8')
const APP_SRC = readFileSync(join(process.cwd(), 'src/App.tsx'), 'utf8')
const INDEX_CSS_SRC = readFileSync(join(process.cwd(), 'src/index.css'), 'utf8')

describe('FIX-116 骨架屏行高对齐', () => {
  it('EntryList 两处 pending 骨架行都声明 min-h-[5.5rem]（88px）', () => {
    const pendingBlocks = ENTRY_LIST_SRC.match(/aria-label="[^"]*加载中"/g) ?? []
    expect(pendingBlocks.length).toBeGreaterThanOrEqual(2)
    const minHCount = ENTRY_LIST_SRC.match(/min-h-\[5\.5rem\]/g) ?? []
    expect(minHCount.length, '时间线 + 稍后读两处骨架行都需预留 88px 行高').toBeGreaterThanOrEqual(2)
  })

  it('App PageSkeleton 行高 88px（不再 h-16=64px 低估）', () => {
    const start = APP_SRC.indexOf('function PageSkeleton')
    expect(start).toBeGreaterThan(0)
    const fn = APP_SRC.slice(start, start + 500)
    expect(fn).toContain('h-[5.5rem]')
    expect(fn).not.toContain('h-16')
  })

  it('行高估算真源唯一：骨架 88px 与 .lumi-row-cv contain-intrinsic-size 同源', () => {
    expect(INDEX_CSS_SRC).toMatch(/\.lumi-row-cv\s*\{[^}]*contain-intrinsic-size:\s*auto 88px/)
  })
})
