/**
 * FIX-080 — Base UI 封装边界基线守卫（source-level 扫描断言）。
 *
 * 现状（已达标，钉住防回潮）：
 * AGENTS.md §UI architecture 约定——feature 组件 MUST NOT 直接 import
 * `@base-ui/react`；Base UI 只允许出现在 components/ui/ 原语内
 * （focus trap / Escape / dismissal / scroll lock / portal / positioning /
 * ARIA 由 Base UI 统一承担，业务面不得二次实现）。
 *
 * 全仓现状核查：@base-ui 的 import 只存在于 components/ui/ 的
 * Dialog / Menu / Popover / RadioGroup / Sheet / Switch / Tabs / Tooltip
 * 八个原语中；唯一在 ui/ 之外出现 `@base-ui` 字样的文件是本目录的
 * fix-273-274 守卫测试（对 Sheet 源码的正则断言，非 import）。
 * 本守卫把这条边界钉成机器断言：白名单 = components/ui/**，
 * __tests__/ 与 generated/ 豁免。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve, sep } from 'node:path'
import { describe, expect, it } from 'vitest'

const srcRoot = resolve(__dirname, '..')

/** 收集 dir 下全部 .ts/.tsx 相对路径（豁免目录名集合）。 */
function collectSources(dir: string, exempt: ReadonlySet<string>, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    const st = statSync(p)
    if (st.isDirectory()) {
      if (exempt.has(name)) continue
      collectSources(p, exempt, out)
    } else if (/\.(ts|tsx)$/.test(name)) {
      out.push(p)
    }
  }
  return out
}

const EXEMPT = new Set(['__tests__', 'generated', 'node_modules'])

describe('FIX-080: Base UI 只能被 components/ui/ 原语 import', () => {
  it('白名单外（components/ui/** 之外）没有任何 @base-ui import', () => {
    const uiDir = `${srcRoot}${sep}components${sep}ui`
    const offenders: string[] = []
    for (const file of collectSources(srcRoot, EXEMPT)) {
      if (file.startsWith(`${uiDir}${sep}`)) continue
      const text = readFileSync(file, 'utf-8')
      // import 形态：from '@base-ui/...' / require('@base-ui/...') /
      // dynamic import('@base-ui/...')——覆盖三条通道。
      if (/from\s+['"]@base-ui\//.test(text) || /import\(\s*['"]@base-ui\//.test(text)) {
        offenders.push(file)
      }
    }
    expect(
      offenders,
      `以下文件绕过 components/ui 直接依赖 Base UI：${offenders.join(', ')}`,
    ).toHaveLength(0)
  })

  it('正面锚点：核心交互原语确实由 Base UI 承担（白名单内仍存在）', () => {
    // 边界守卫的反向锚点：若有人把原语整体换掉（去 Base UI 化），
    // 白名单断言会 vacuously 通过——这里钉住已知迁移成果仍在。
    const pairs: ReadonlyArray<readonly [string, string]> = [
      ['components/ui/Dialog.tsx', "@base-ui/react/dialog'"],
      ['components/ui/Sheet.tsx', "@base-ui/react/drawer'"],
      ['components/ui/Popover.tsx', '@base-ui/react/'],
      ['components/ui/Menu.tsx', '@base-ui/react/'],
      ['components/ui/Switch.tsx', '@base-ui/react/switch'],
      ['components/ui/Tabs.tsx', '@base-ui/react/'],
      ['components/ui/Tooltip.tsx', '@base-ui/react/'],
      ['components/ui/RadioGroup.tsx', '@base-ui/react/'],
    ]
    for (const [rel, marker] of pairs) {
      expect(readFileSync(resolve(srcRoot, rel), 'utf-8'), rel).toContain(marker)
    }
  })
})
