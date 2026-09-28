/**
 * FIX-299 — CJK+Latin 混排基线稳健性（字体栈 + 行高）。
 *
 * 背景：界面字体走 --lumi-font-sans（index.css body）。中文在 system-ui
 * 无字形时按 CJK 链回退（macOS PingFang SC → Hiragino Sans GB →
 * Windows Microsoft YaHei → Linux/Android Noto Sans CJK SC），不同回退
 * 字体的 ascent/descent 切分不同——行高 1.0（leading-none）时基线在
 * 行盒内的位置随平台漂移，中文按钮/标签出现「基线变化」。
 *
 * 修复：
 * 1. 字体栈：移除死条目 'SN Pro'（Folo 品牌字体，未打包；拉丁字符在
 *    system-ui 已命中、CJK 字符它无字形——任何平台都不可达，删除为
 *    零视觉变化），CJK 链保持平台覆盖面排序，generic sans-serif 收尾；
 * 2. 行高：全部 CJK 文本的 leading-none（1.0）→ leading-tight（1.25，
 *    Tailwind text-sm 等默认行高同档）——半行距均分使基线位置在任一
 *    回退字体下稳定；共 19 处（设置标签 / 底部导航标签 / 徽标 / 关闭
 *    字形按钮）。
 *
 * 守卫：components 内禁止再引入 leading-none（CJK 文本行盒不稳）；
 * tokens.css 钉住字体栈形态。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const srcRoot = resolve(__dirname, '..')

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

describe('FIX-299 CJK 字体栈与行高稳健性', () => {
  it('--lumi-font-sans：system-ui 起、CJK 链按平台排序、generic 收尾、无死条目', () => {
    const tokens = readFileSync(resolve(srcRoot, 'styles/tokens.css'), 'utf8')
    const stack = tokens.match(/--lumi-font-sans:\s*([^;]+);/)?.[1] ?? ''
    const families = stack.split(',').map((s) => s.trim().replace(/^'|'$/g, ''))
    expect(families[0]).toBe('system-ui')
    expect(families).toContain('PingFang SC')
    expect(families).toContain('Hiragino Sans GB')
    expect(families).toContain('Microsoft YaHei')
    expect(families).toContain('Noto Sans CJK SC')
    expect(families[families.length - 1]).toBe('sans-serif')
    // 未打包的品牌字体（拉丁 only）在 system-ui 之后不可达：禁止回潮
    expect(stack).not.toContain('SN Pro')
  })

  it('components 内不再有 leading-none（CJK 文本行盒 ≥1.25 行高）', () => {
    const offenders: string[] = []
    for (const file of walk(srcRoot)) {
      const src = readFileSync(file, 'utf8')
      if (/leading-none/.test(src)) {
        offenders.push(file.slice(srcRoot.length + 1))
      }
    }
    expect(offenders).toEqual([])
  })

  it('reader 无衬线栈与界面栈同构（ui-sans-serif/system-ui + 同一 CJK 链）', () => {
    const readerStyle = readFileSync(resolve(srcRoot, 'lib/reader-style.ts'), 'utf8')
    for (const family of [
      'PingFang SC',
      'Hiragino Sans GB',
      'Microsoft YaHei',
      'Noto Sans CJK SC',
    ]) {
      expect(readerStyle).toContain(`"${family}"`)
    }
  })
})
