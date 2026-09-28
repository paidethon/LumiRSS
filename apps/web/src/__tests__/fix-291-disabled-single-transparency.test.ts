/**
 * FIX-291 — 禁用语义仅作用一次（source-level 断言）。
 *
 * 背景：accent-soft / success-soft / danger-soft 是 rgba 淡底（自带透明度，
 * themes.css），`.lumi-glass` 是 72% 透明着色表面（index.css）。禁用文字若
 * 落在这类「本身带透明度」的表面上再叠 `disabled:opacity-50`，透明度乘两
 * 次：淡底几乎消失、文字对比被双乘，可读性低于设计预期的单一禁用档。
 *
 * 审计结论（2026-09 R2，web12）：
 * - Button / IconButton / Select / Menu / Switch 等原语的 disabled 只在不
 *   透明 token 表面上叠一层 opacity —— 单次作用，保留；
 * - 唯一双乘实例：EntryList 批量操作按钮（bg-accent-soft 淡底 +
 *   disabled:opacity-50，且初始未选中时恒为禁用态）→ 收敛为单一 token：
 *   disabled 去淡底 + text-[var(--lumi-text-disabled)]（无额外 alpha）；
 * - .lumi-glass 表面（顶栏/底栏/底部 sheet）现不含禁用控件（审计
 *   MobilePageHeader / MobileTabBar / ReaderAaPanel 均无 disabled）。
 *
 * 本测试为 source-level 断言（jsdom 无真实级联样式），防止回潮：
 * 任何组件不得在同一个 className 里同时出现「禁用 opacity」与
 * 「自带透明度的表面（*-soft 淡底）」。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const srcRoot = resolve(__dirname, '../')

function walk(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    const st = statSync(p)
    if (st.isDirectory()) {
      if (name === '__tests__') continue
      out.push(...walk(p))
    } else if (name.endsWith('.tsx')) {
      out.push(p)
    }
  }
  return out
}

/** 禁用透明语义（disabled / Base UI data-disabled 两种写法） */
const DISABLED_OPACITY = /(?:data-)?disabled:opacity-\d+/
/** 自带透明度的表面 token（themes.css 中均为 rgba 淡底） */
const TRANSLUCENT_BG = /bg-\[var\(--lumi-[a-z]+-soft\)\]/

describe('FIX-291 禁用语义仅作用一次', () => {
  it('禁用 opacity 不得与自带透明度的淡底表面同 className（双乘透明）', () => {
    const offenders: string[] = []
    for (const file of walk(srcRoot)) {
      const text = readFileSync(file, 'utf8')
      // 逐 className 字符串检查（引号内的一段才算同一元素）
      for (const m of text.matchAll(/"([^"\n]*)"/g)) {
        if (DISABLED_OPACITY.test(m[1]) && TRANSLUCENT_BG.test(m[1])) {
          offenders.push(`${join(file, '')}: …${m[1].slice(0, 80)}…`)
        }
      }
    }
    expect(offenders).toEqual([])
  })

  it('EntryList 批量按钮禁用态已收敛为单一 token（去淡底 + text-disabled，无 opacity）', () => {
    const text = readFileSync(
      resolve(srcRoot, 'components/EntryList.tsx'),
      'utf8',
    )
    // bg-accent-soft 的批量按钮：禁用语义必须只有一条收敛路径
    const softButtons = [...text.matchAll(/className="([^"]*accent-soft[^"]*)"/g)].map(
      (m) => m[1],
    )
    expect(softButtons.length).toBeGreaterThan(0)
    for (const cls of softButtons) {
      if (cls.includes('disabled:')) {
        expect(cls).toContain('disabled:bg-transparent')
        expect(cls).toContain('disabled:text-[var(--lumi-text-disabled)]')
        expect(cls).not.toMatch(DISABLED_OPACITY)
      }
    }
  })

  it('单一禁用文字 token --lumi-text-disabled 在两主题均有定义（收敛目标存在）', () => {
    const themes = readFileSync(resolve(srcRoot, 'styles/themes.css'), 'utf8')
    expect(themes.match(/--lumi-text-disabled:/g)?.length).toBe(2)
  })
})
