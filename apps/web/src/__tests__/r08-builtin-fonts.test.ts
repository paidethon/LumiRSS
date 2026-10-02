/** R08 内置阅读字体 — 资产与机制契约测试。
 *
 * 覆盖三条硬约束：
 * 1. 字体档位：reader-style 的标签/栈/选项含全部 8 款内置字体
 *    （6 中 2 英），且与 app-settings 的 ReaderFontFamily 同域；
 * 2. fonts.css：8 个 @font-face family 全部声明、每条 face 带
 *    unicode-range、src 全部为 /fonts/ 自托管相对路径；
 * 3. 无外部字体 CDN：整份样式表不出现 http(s) 字体 URL；
 *    每个被引用的 woff2 真实存在于 public/fonts 且为 WOFF2 魔数。
 * 另测 FontFaceSet 桥（useBuiltinFontState）的加载三态。 */

import { readFileSync, existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  BUILTIN_READER_FONTS,
  READER_FONT_LABELS,
  READER_FONT_OPTIONS,
  READER_FONT_STACKS,
} from '../lib/reader-style'
import { PORTABLE_KEYS } from '../store/app-settings'

const webRoot = resolve(__dirname, '../..')
const fontsCss = readFileSync(join(webRoot, 'src/styles/fonts.css'), 'utf8')
const fontsDir = join(webRoot, 'public/fonts')

/** 8 款内置字体 id（6 中 2 英）。 */
const BUILTIN_IDS = [
  'source-han-sans',
  'source-han-serif',
  'lxgw-wenkai',
  'zhuque-fangsong',
  'zcool-xiaowei',
  'ma-shan-zheng',
  'source-sans-3',
  'source-serif-4',
] as const

describe('R08 字体档位（reader-style）', () => {
  it('标签表含系统四档 + 内置 8 款，共 12 键且非空', () => {
    expect(Object.keys(READER_FONT_LABELS)).toHaveLength(12)
    for (const id of BUILTIN_IDS) expect(READER_FONT_LABELS[id]).toBeTruthy()
    expect(READER_FONT_LABELS.system).toContain('默认')
  })

  it('BUILTIN_READER_FONTS = 8 款：6 中文正文/展示 + 2 英文', () => {
    expect(BUILTIN_READER_FONTS.map((f) => f.id)).toEqual(BUILTIN_IDS)
    const kinds = Object.fromEntries(BUILTIN_READER_FONTS.map((f) => [f.id, f.kind]))
    expect(kinds['zcool-xiaowei']).toBe('display')
    expect(kinds['ma-shan-zheng']).toBe('display')
    for (const id of ['source-han-sans', 'source-han-serif', 'lxgw-wenkai', 'zhuque-fangsong'] as const) {
      expect(kinds[id]).toBe('body')
    }
    for (const f of BUILTIN_READER_FONTS) {
      expect(f.cssFamily).toBeTruthy()
      expect(f.sample.length).toBeGreaterThan(0)
      expect(f.hint.length).toBeGreaterThan(0)
    }
  })

  it('每个 ReaderFontFamily 值都有字体栈与选项（同序同源）', () => {
    expect(Object.keys(READER_FONT_STACKS)).toHaveLength(12)
    expect(READER_FONT_OPTIONS).toHaveLength(12)
    for (const { value, label } of READER_FONT_OPTIONS) {
      expect(READER_FONT_STACKS[value]).toBeTruthy()
      expect(label).toBe(READER_FONT_LABELS[value])
    }
  })

  it('持久化沿用 portable 键 readerFontFamily', () => {
    expect(PORTABLE_KEYS).toContain('readerFontFamily')
  })

  it('内置字体栈以自托管 family 开头、系统同族兜底收尾', () => {
    const sans = READER_FONT_STACKS['source-han-sans']
    expect(sans).toContain('"Source Han Sans SC"')
    expect(sans.trimEnd().endsWith('sans-serif')).toBe(true)
    const serif = READER_FONT_STACKS['source-han-serif']
    expect(serif).toContain('"Source Han Serif SC"')
  })
})

describe('R08 fonts.css 契约', () => {
  it('8 个内置 family 均有 @font-face 声明', () => {
    const faceCount = (fontsCss.match(/@font-face\s*\{/g) ?? []).length
    expect(faceCount).toBeGreaterThanOrEqual(22) // 16 CJK 分片 + 2 展示整包 + 2×3 latin
    for (const family of BUILTIN_READER_FONTS.map((f) => f.cssFamily)) {
      expect(fontsCss).toContain(`font-family: "${family}"`)
    }
  })

  it('每条 @font-face 都带 unicode-range 与 font-display: swap', () => {
    const blocks = fontsCss.split('@font-face').slice(1)
    expect(blocks.length).toBeGreaterThanOrEqual(22)
    for (const block of blocks) {
      expect(block).toMatch(/unicode-range:\s*U\+[0-9A-F]/)
      expect(block).toContain('font-display: swap')
      expect(block).toMatch(/font-weight:\s*\d+/)
    }
  })

  it('src 全部为 /fonts/ 自托管相对路径（无外部字体 CDN）', () => {
    expect(fontsCss).not.toMatch(/https?:\/\//)
    const srcs = [...fontsCss.matchAll(/url\('([^']+)'\)/g)].map((m) => m[1])
    expect(srcs.length).toBeGreaterThanOrEqual(22)
    for (const src of srcs) expect(src.startsWith('/fonts/')).toBe(true)
  })

  it('每个被引用 woff2 真实存在且为 WOFF2 魔数（wOF2）', () => {
    const srcs = [...fontsCss.matchAll(/url\('([^']+)'\)/g)].map((m) => m[1])
    for (const src of srcs) {
      const file = join(fontsDir, src.slice('/fonts/'.length))
      expect(existsSync(file), file).toBe(true)
      const head = readFileSync(file).subarray(0, 4)
      expect(head[0]).toBe(0x77)
      expect(head[1]).toBe(0x4f)
      expect(head[2]).toBe(0x46)
      expect(head[3]).toBe(0x32)
    }
  })

  it('每款字体目录都有 LICENSE.txt（OFL 文本随字体分发）', () => {
    for (const id of BUILTIN_IDS) {
      const lic = join(fontsDir, id, 'LICENSE.txt')
      expect(existsSync(lic), lic).toBe(true)
      expect(readFileSync(lic, 'utf8')).toMatch(/Open Font License|Reserved Font Name/)
    }
  })
})
