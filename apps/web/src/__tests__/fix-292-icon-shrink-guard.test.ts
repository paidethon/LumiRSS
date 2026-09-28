/**
 * FIX-292 — 图标 SVG 的 flex-shrink 约束守卫（source-level 断言）。
 *
 * 背景：长标题行里图标若可被 flex 压缩，会出现「文字截断、图标被压扁变
 * 形」。CSS Flexbox 的 automatic minimum size 规则给了两条天然防线：
 * 1. 图标带确定尺寸（Tailwind `size-*` / `w-*`/`h-*`）→ specified size
 *    suggestion 即为 min-width:auto 下限，不可被压缩；
 * 2. 图标显式 `shrink-0`（Sidebar / SidebarCollapsedRail 的
 *    `icon16 = 'size-4 shrink-0'` 是仓库既定模式；Button 的 loading
 *    spinner 也带 shrink-0）。
 * 二者缺一的图标若与 `truncate` 标签同处 `flex items-center` 行，就会
 * 被压缩——本守卫禁止该组合。
 *
 * 审计结论（2026-09 R2，web12）：仓库内全部图标位置均已满足其一——
 * - IconButton / EntryActionButtons（btnBase size-7 或 min-w-11 固定容器）：
 *   图标在固定盒内，物理上不可能被压缩；
 * - 行内图标一律带 size-*（如 PreviewStage 的 ExternalLink size-3 +
 *   truncate 链接）或 shrink-0（Sidebar icon16）。
 * 因此本项为 BASELINE_OK：无实修点，守卫防回潮（新增行内图标若既无
 * 确定尺寸也无 shrink-0 且紧邻 truncate 标签 → 测试红）。
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

/** 确定尺寸类（Tailwind）：作为 flex 项的 specified size suggestion，
 * 使 automatic minimum size 固定在该值，图标不可被压缩。 */
const DEFINITE_SIZE = /(?:size|w|h)-(?:\d+(?:\.\d+)?|full|screen)/

/** 仓库既定的图标 class 常量（其定义本身被下面的锚点断言钉住为
 * 'size-4 shrink-0'）——props 里引用这些标识符视同已满足约束。 */
const SHRINK_CONSTANTS = /className=\{(?:cx\()?'?(icon16|iconCls)'?\)?/

describe('FIX-292 行内图标不可被长标签压缩', () => {
  it('truncate 标签所在 flex 行内，紧邻图标必须带 shrink-0 或确定尺寸', () => {
    const offenders: string[] = []
    for (const file of walk(srcRoot)) {
      const lines = readFileSync(file, 'utf8').split('\n')
      for (let i = 0; i < lines.length; i++) {
        if (!lines[i].includes('truncate')) continue
        const up = lines.slice(Math.max(0, i - 8), i).join('\n')
        // 仅约束「flex items-center 行 + 8 行内出现 aria-hidden 图标」的形态
        if (!/items-center/.test(up)) continue
        const icon = up.match(/<([A-Z][A-Za-z0-9]+)\s+aria-hidden([^>]*)>/s)
        if (!icon) continue
        const props = icon[2]
        if (/shrink-0/.test(props)) continue
        if (DEFINITE_SIZE.test(props)) continue
        if (SHRINK_CONSTANTS.test(props)) continue
        offenders.push(`${file}:${i + 1} <${icon[1]}${props.replace(/\s+/g, ' ')}>`)
      }
    }
    expect(offenders).toEqual([])
  })

  it('既有模式锚点：Sidebar/SidebarCollapsedRail 行内图标常量带 shrink-0；Button spinner 带 shrink-0', () => {
    const sidebar = readFileSync(resolve(srcRoot, 'Sidebar.tsx'), 'utf8')
    expect(sidebar).toMatch(/icon16 = 'size-4 shrink-0'/)
    const rail = readFileSync(resolve(srcRoot, 'SidebarCollapsedRail.tsx'), 'utf8')
    expect(rail).toMatch(/iconCls = 'size-4 shrink-0'/)
    const button = readFileSync(resolve(srcRoot, 'ui/Button.tsx'), 'utf8')
    expect(button).toMatch(/data-loading-spinner=""\s*\n\s*className="size-4 shrink-0/)
  })
})
