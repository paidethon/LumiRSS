/** FIX-111 — 过宽动画守卫：全库禁止 transition: all。
 *
 * 契约（审计缺陷类：`transition: all` 会让非预期属性（width/height/
 * box-shadow/color…）全部进动画管线——低性能设备上滚动/交互掉帧，
 * reduced-motion 下也扩大了需要被抑制的面）：
 * 1. 全代码库（src/**，含 ts/tsx/css）不存在 `transition-all` Tailwind
 *    类与 `transition: all` / `transition-property: all` 声明；
 * 2. 例外必须登记在下方 ALLOWLIST（文件 + 理由），空表 = 无例外；
 * 3. 动画只允许 opacity/transform（cheap properties）——交由既有
 *    review 把关，本守卫拦截的是「全属性」这一最坏形态。
 *
 * 修复实例：RecentReads 面板自绘开关 thumb 曾用 transition-all
 * （left 位移）——改为 transform 位移 + transition-transform（与
 * ui/Switch 原语同款，只动 transform）。
 *
 * 突变注入验证：给任意组件加回 `transition-all` → 静态扫描变红，
 * 并指认文件与行号。
 */

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/** 例外登记处：文件路径（相对 src）→ 理由。空表 = 零例外。
 * 新增例外必须同时给出「为什么 all 是必要的」理由，否则收窄到具体属性。 */
const ALLOWLIST: Readonly<Record<string, string>> = {}

/** 递归收集 src 下的 .ts/.tsx/.css 源码（排除测试自身）。 */
function collectSourceFiles(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) {
      if (name === '__tests__') continue
      out.push(...collectSourceFiles(full))
    } else if (
      ((name.endsWith('.ts') || name.endsWith('.tsx')) && !name.includes('.test.')) ||
      name.endsWith('.css')
    ) {
      out.push(full)
    }
  }
  return out
}

/** 命中行：transition-all Tailwind 类 / transition: all / transition-property: all。 */
function allTransitionSites(text: string): number[] {
  const sites: number[] = []
  const patterns = [
    /(^|[\s'"`])transition-all[\s'"`]/, // Tailwind class（含模板字符串/类数组）
    /transition\s*:\s*all[\s;!]/, // CSS 声明
    /transition-property\s*:\s*all/, // CSS 属性级声明
  ]
  for (const pattern of patterns) {
    for (const m of text.matchAll(new RegExp(pattern.source, 'g'))) {
      sites.push(text.slice(0, m.index ?? 0).split('\n').length)
    }
  }
  return sites
}

describe('FIX-111 transition:all 全库守卫', () => {
  it('静态扫描：src 下不存在 transition-all / transition: all（例外须登记 ALLOWLIST）', () => {
    const srcDir = join(process.cwd(), 'src')
    const offenders = collectSourceFiles(srcDir)
      .map((file) => {
        const rel = file.slice(srcDir.length + 1)
        const sites = allTransitionSites(readFileSync(file, 'utf8'))
        return { rel, sites, allowed: rel in ALLOWLIST }
      })
      .filter((entry) => entry.sites.length > 0 && !entry.allowed)
    expect(
      offenders.map((o) => `${o.rel}:${o.sites.join(',')}`),
      '过宽 transition 被禁用；如确有必要请在 ALLOWLIST 登记理由',
    ).toEqual([])
  })
})
