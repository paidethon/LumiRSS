/**
 * FIX-079 — 开关行文案基线：标题、辅助说明与右侧控件布局已收敛，
 * 无重复的「某某开关」可见文字。
 *
 * 现状（已达标，钉住防回潮）：
 * - Switch 原语只渲染控件本体，绝不渲染可见文字；label 仅作无障碍
 *   名称（行内有可见标题时以 aria-labelledby 优先）；
 * - SettingItem 的 ToggleRowView：可见标题在左（<label htmlFor> 关联
 *   点击 + aria-labelledby），右侧只有控件本体；
 * - 可见文本里不允许出现「开关」尾缀（aria-label 回退值不算可见文本）。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const read = (rel: string): string => readFileSync(resolve(__dirname, '..', rel), 'utf-8')

const switchPrimitive = read('components/ui/Switch.tsx')
const settingItem = read('components/settings/SettingItem.tsx')

describe('FIX-079: 开关行标题/说明/控件布局', () => {
  it('Switch 原语只渲染控件本体：无可见文字节点，名称走 aria-label/labelledby', () => {
    // label prop 只进 aria 属性，不作为 JSX 文本渲染
    expect(switchPrimitive).toMatch(/aria-label=\{labelledby \? undefined : label\}/)
    expect(switchPrimitive).toMatch(/aria-labelledby=\{labelledby\}/)
    // 组件 JSX 内没有把 {label} 作为可见子节点渲染（不含 >{label}< 形态）
    expect(switchPrimitive).not.toMatch(/>\s*\{label\}\s*</)
  })

  it('SettingItem 开关行：可见标题 label htmlFor + aria-labelledby，控件本体在右', () => {
    // ToggleRowView：标题 id 关联（labelFor=switchId + labelledby=titleId）
    expect(settingItem).toMatch(/labelFor=\{switchId\}/)
    expect(settingItem).toMatch(/labelledby=\{titleId\}/)
    expect(settingItem).toMatch(/labelledby=\{titleId\}/)
  })

  it('全仓库设置面不再渲染重复的「XX开关」可见文案（文本节点形态）', () => {
    // 可见文本形态：>文字开关< 直接输出；label={`${...}开关`} 是 aria
    // 回退名，不属于可见文案，不在本守卫范围。
    const offenders: string[] = []
    const { readdirSync, statSync } = require('node:fs') as typeof import('node:fs')
    const { join } = require('node:path') as typeof import('node:path')
    const srcRoot = resolve(__dirname, '..')
    const walk = (dir: string): void => {
      for (const name of readdirSync(dir)) {
        const p = join(dir, name)
        const st = statSync(p)
        if (st.isDirectory()) {
          if (name === '__tests__' || name === 'generated') continue
          walk(p)
        } else if (/\.tsx$/.test(name)) {
          const text = readFileSync(p, 'utf-8')
          if (/>[^<>{}]*开关</.test(text) && p.includes('settings')) {
            offenders.push(p)
          }
        }
      }
    }
    walk(resolve(srcRoot, 'components/settings'))
    expect(offenders, `发现重复开关可见文案：${offenders.join(', ')}`).toHaveLength(0)
  })
})
