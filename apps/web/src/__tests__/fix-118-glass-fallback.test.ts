/** FIX-118 — 玻璃材质（backdrop-filter）滚动性能与不透明降级守卫。
 *
 * 现状核验（BASELINE 收紧）：blur 只允许出现在 index.css 的
 * `.lumi-glass` 材质块（MobilePageHeader / MobileTabBar / Sheet 底部
 * 面板共用；正文与长列表明确保持稳定底色），且必须带四条降级路径：
 * 1. 无 backdrop-filter 支持（@supports 不成立）→ 基础规则即实色
 *    var(--lumi-elevated)（降级默认态）；
 * 2. prefers-reduced-transparency: reduce → 实色 + 无 blur；
 * 3. prefers-reduced-motion: reduce（FIX-118 新增：低性能设备唯一
 *    标准化信号；blur 每帧重采样背景是低端 GPU 掉帧源）→ 实色 + 无 blur；
 * 4. html[data-glass='off']（用户显式关闭）→ 实色 + 无 blur。
 *
 * 突变注入验证：删掉任一 media 降级块 → 对应断言变红；在组件层加
 * Tailwind backdrop-blur-* → 「blur 只在 .lumi-glass」断言变红。
 */

import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { readdirSync, statSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const INDEX_CSS = readFileSync(join(process.cwd(), 'src/index.css'), 'utf8')

function collectSourceFiles(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) {
      if (name === '__tests__') continue
      out.push(...collectSourceFiles(full))
    } else if ((name.endsWith('.ts') || name.endsWith('.tsx')) && !name.includes('.test.')) {
      out.push(full)
    }
  }
  return out
}

describe('FIX-118 玻璃材质降级守卫', () => {
  it('backdrop-filter 只存在于 .lumi-glass 材质块（组件层禁用 backdrop-blur-*）', () => {
    const offenders = collectSourceFiles(join(process.cwd(), 'src'))
      .map((file) =>
        // Tailwind 类（backdrop-blur-<n>）或 CSS 属性用法；纯注释提及不算
        /backdrop-blur-[a-z0-9]|backdrop-filter\s*:/.test(readFileSync(file, 'utf8')) ? file : null)
      .filter((v): v is string => v !== null)
    expect(offenders).toEqual([])
    // CSS 侧：实际启用的 blur 只有 .lumi-glass 启用规则一对
    //（-webkit- 前缀 + 标准 = 2 处声明；blur(1px) 是 @supports 能力探针）
    expect(INDEX_CSS.match(/backdrop-filter:\s*blur\(18px\)/g)?.length).toBe(2)
  })

  it('实色基础态 + 三条媒体/属性降级（transparency / motion / data-glass=off）', () => {
    // 1) 基础规则实色（@supports 外）
    expect(INDEX_CSS).toMatch(/\.lumi-glass\s*\{[^}]*background:\s*var\(--lumi-elevated\)/)
    // 2) prefers-reduced-transparency 降级
    expect(INDEX_CSS).toMatch(
      /@media \(prefers-reduced-transparency: reduce\) \{\s*html:not\(\[data-glass='off'\]\) \.lumi-glass \{[^}]*backdrop-filter: none/s,
    )
    // 3) FIX-118：prefers-reduced-motion 降级（低性能设备回退实色）
    expect(INDEX_CSS).toMatch(
      /@media \(prefers-reduced-motion: reduce\) \{\s*html:not\(\[data-glass='off'\]\) \.lumi-glass \{[^}]*backdrop-filter: none/s,
    )
    // 4) 显式关闭（data-glass='off'）
    expect(INDEX_CSS).toMatch(
      /html\[data-glass='off'\] \.lumi-glass \{[^}]*backdrop-filter: none/s,
    )
  })
})
