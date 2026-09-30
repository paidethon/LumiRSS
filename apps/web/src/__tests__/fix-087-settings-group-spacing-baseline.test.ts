/**
 * FIX-087 — 设置页分组密度/留白与开关命中区基线守卫（source-level
 * 断言，风格同 fix-079-switch-row-baseline）。
 *
 * 裁决：BASELINE_OK。分组节奏与命中区保护已成型（Folo 实测规格）：
 * - 分组标题（SettingItem type:'title'）：mt-8 + first:mt-0 —— 组间留白
 *   32px、首组贴顶，不过密也不失衡；标题自带 margin 隔断故不参与
 *   divide-y；
 * - 行密度统一：RowShell 行 py-3（12px 上下），分组内以
 *   divide-[var(--lumi-separator)] 细分隔；
 * - 长说明不挤压开关命中区：RowShell 左列 min-w-0（说明在自己的列内
 *   换行）+ 右列 shrink-0；Switch 轨道 h-6 w-11 shrink-0，再以透明
 *   伪元素 after:-inset-y-2.5 把可点区撑到 ≥44×44——说明再长，
 *   开关命中区几何不变。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const read = (rel: string): string => readFileSync(resolve(__dirname, '..', rel), 'utf-8')

const settingItem = read('components/settings/SettingItem.tsx')
const switchPrimitive = read('components/ui/Switch.tsx')

describe('FIX-087: 设置分组留白节奏', () => {
  it('分组标题 mt-8 + first:mt-0（组间 32px、首组贴顶，无过密/失衡）', () => {
    expect(settingItem).toMatch(
      /mt-8 px-0\.5 text-\[13px\] font-bold text-\[var\(--lumi-text-tertiary\)\] first:mt-0/,
    )
  })

  it('行密度统一 py-3，组内行以 separator 细分隔（标题行不参与 divide）', () => {
    expect(settingItem).toMatch(/flex items-center justify-between gap-4 py-3/)
    expect(settingItem).toContain('divide-y divide-[var(--lumi-separator)]')
    expect(settingItem).toMatch(/isTitle && 'border-t-0 \[&&:not\(:first-child\)\]:pt-0'/)
  })
})

describe('FIX-087: 长说明不挤压开关命中区', () => {
  it('RowShell 左列 min-w-0 + 右列 shrink-0（说明换行吃自己的列）', () => {
    expect(settingItem).toMatch(/<div className="min-w-0">/)
    expect(settingItem).toMatch(
      /<div className="flex shrink-0 items-center gap-2\.5">\{children\}<\/div>/,
    )
  })

  it('Switch 轨道 h-6 w-11 shrink-0 + 透明伪元素撑出 ≥44px 命中区', () => {
    expect(switchPrimitive).toMatch(/relative inline-flex h-6 w-11 shrink-0/)
    expect(switchPrimitive).toContain('after:-inset-y-2.5') // 24px 轨道上下各撑 10px → 44px
    expect(switchPrimitive).toContain('w-11') // 横向命中区 = 44px
  })
})
