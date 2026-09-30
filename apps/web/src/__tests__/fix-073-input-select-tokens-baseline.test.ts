/**
 * FIX-073 — 输入框 / 选择器 / 搜索框 token 一致性基线守卫
 * （source-level 扫描断言，风格同 fix-072-button-size-variants）。
 *
 * 裁决：BASELINE_OK。边框/背景/禁用态已统一在 --lumi-* token 上：
 * - Select 原语：border-[var(--lumi-border)] + bg-[var(--lumi-surface)]
 *   + data-lumi-focus-ring（FIX-293 不可覆盖焦点环）+
 *   disabled:cursor-not-allowed disabled:opacity-50（禁用不伪装可编辑）；
 * - 仓库共享的 parts 常量 inputClass（new2xx/new3xx 各面板唯一输入框
 *   样式来源）字节级一致，同为 border/bg 两 token + radius-md；
 * - 全仓扫描：<input>/<select>/<textarea> 的 className 零硬编码调色板
 *   色类（border-gray-300 之类）——边框与背景只允许 --lumi-* token。
 *
 * 已知长尾（feature 文件，越出本批文件边界，记录不修）：
 * - 散装文本输入未挂 data-lumi-focus-ring，焦点环走 UA 默认 outline
 *   （可见性与 a11y 门不冲突，仅色值非 token）；
 * - 19 处 disabled 输入自身无 disabled: 类，依赖 UA 灰化。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const read = (rel: string): string => readFileSync(resolve(__dirname, '..', rel), 'utf-8')

const srcRoot = resolve(__dirname, '..')
const select = read('components/ui/Select.tsx')

/** 收集 .ts/.tsx 相对路径（豁免测试与生成物）。 */
function collectSources(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    const st = statSync(p)
    if (st.isDirectory()) {
      if (name === '__tests__' || name === 'generated' || name === 'node_modules') continue
      collectSources(p, out)
    } else if (/\.(ts|tsx)$/.test(name)) {
      out.push(p)
    }
  }
  return out
}

describe('FIX-073: Select 原语的边框/背景/焦点环/禁用态', () => {
  it('边框+背景用 --lumi token，焦点环挂 data-lumi-focus-ring（FIX-293）', () => {
    expect(select).toContain('border-[var(--lumi-border)]')
    expect(select).toContain('bg-[var(--lumi-surface)]')
    expect(select).toContain('data-lumi-focus-ring=""')
  })

  it('禁用态不伪装成可编辑：cursor-not-allowed + opacity-50', () => {
    expect(select).toContain('disabled:cursor-not-allowed')
    expect(select).toContain('disabled:opacity-50')
  })
})

describe('FIX-073: 共享 parts inputClass 常量字节级一致', () => {
  it('new2xx/new3xx 各面板的 inputClass 是同一条 canonical 串', () => {
    const canonical =
      'w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 text-sm text-[var(--lumi-text-primary)]'
    const partsFiles = [
      'components/new271/panel.tsx',
      'components/new281/parts.tsx',
      'components/new311/parts.tsx',
      'components/new331/../new311/parts.tsx',
      'components/new341/parts.tsx',
      'components/new371/parts.tsx',
      'components/new381/parts.tsx',
      'components/new391/parts.tsx',
    ]
    for (const rel of [...new Set(partsFiles)]) {
      const text = read(rel)
      const m = text.match(/export const inputClass =\s*\n?\s*'([^']*)'/)
      expect(m, `${rel} 应导出 inputClass 常量`).not.toBeNull()
      expect(m![1], `${rel} inputClass 漂移`).toBe(canonical)
    }
  })

  it('canonical 串只用 --lumi token（border/bg/radius/text 四类）', () => {
    // 上一条已钉具体值；这里钉它的 token 属性，防「同步漂移到非 token」。
    const m = read('components/new311/parts.tsx').match(
      /export const inputClass =\s*\n?\s*'([^']*)'/,
    )!
    expect(m[1]).toMatch(/border border-\[var\(--lumi-border\)\]/)
    expect(m[1]).toMatch(/bg-\[var\(--lumi-surface\)\]/)
    expect(m[1]).toMatch(/rounded-\[var\(--lumi-radius-md\)\]/)
    expect(m[1]).toMatch(/text-\[var\(--lumi-text-primary\)\]/)
  })
})

describe('FIX-073: 全仓输入控件零硬编码调色板色', () => {
  it('<input>/<select>/<textarea> className 无 border/bg-*-{palette} 类', () => {
    const offenders: string[] = []
    const paletteClass =
      /(?:border|bg)-(?:gray|slate|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}/
    for (const file of collectSources(srcRoot)) {
      const text = readFileSync(file, 'utf-8')
      const re = /<(input|select|textarea)\b/g
      let m: RegExpExecArray | null
      while ((m = re.exec(text))) {
        // 开标签通常跨多行；取到下一个 '>'（模板字符串内不含裸 '>' 的
        // className 值，极端形态漏扫是可接受的守卫误差）。
        const openEnd = text.indexOf('>', m.index)
        if (openEnd === -1) continue
        const open = text.slice(m.index, openEnd + 1)
        const cls = open.match(/className=(?:"([^"]*)"|\{cx\(\s*`([^`]*)`)/)
        const value = cls ? (cls[1] ?? cls[2] ?? '') : ''
        if (paletteClass.test(value)) offenders.push(`${file}: ${value.match(paletteClass)![0]}`)
      }
    }
    expect(offenders, `输入控件出现硬编码调色板色：${offenders.join('; ')}`).toHaveLength(0)
  })
})
