/**
 * FIX-084 — 表单标签/错误文案换行不使同行控件错位（基线守卫，
 * source-level 断言，风格同 fix-079-switch-row-baseline）。
 *
 * 裁决：BASELINE_OK。行内布局已按「标签列可换行、控件列不可挤压」
 * 收敛，换行只发生在文案自己的列里：
 * - SettingItem RowShell（设置面唯一的声明式行壳）：flex items-center
 *   justify-between gap-4；左列 min-w-0（长标签/长说明在自己列内换行），
 *   右列 shrink-0（控件盒稳定，不被文案换行推移/挤压）；
 * - 行内文案全部块级落位：标题/说明在左列纵向堆叠（label + 块级 <p>），
 *   不与右侧控件同行竞争；表单域惯用法 label 文字在控件上方
 *   （label 以 flex-col/block 包裹控件）；
 * - 错误/警示文案为块级 <p role="alert">（或状态徽章 span），截断处
 *   经 title 属性保留全文。
 * （不采用「danger 文案 × 输入控件窗口相邻」扫描：JSX 文本窗口无法
 * 区分同行兄弟与同分区先后块，误报率高，见本批核查记录。）
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const read = (rel: string): string => readFileSync(resolve(__dirname, '..', rel), 'utf-8')

const settingItem = read('components/settings/SettingItem.tsx')
const entryList = read('components/EntryList.tsx')

describe('FIX-084: 设置行壳——标签列可换行、控件列稳定', () => {
  it('RowShell：items-center justify-between + 左列 min-w-0 + 右列 shrink-0', () => {
    expect(settingItem).toMatch(/flex items-center justify-between gap-4 py-3/)
    expect(settingItem).toMatch(/<div className="min-w-0">/)
    expect(settingItem).toMatch(
      /<div className="flex shrink-0 items-center gap-2\.5">\{children\}<\/div>/,
    )
  })

  it('RowShell 标签 leading-tight：换行行距稳定，控件垂直居中不跳', () => {
    expect(settingItem).toMatch(/text-sm font-medium leading-tight text-\[var\(--lumi-text-primary\)\]/)
  })

  it('说明文字块级 <p> 落在标题下方（min-w-0 列内换行，不与控件同行）', () => {
    expect(settingItem).toMatch(
      /<p className="mt-1 text-xs leading-relaxed text-\[var\(--lumi-text-secondary\)\]">/,
    )
  })
})

describe('FIX-084: 错误文案块级落位正面锚点', () => {
  it('批量失败文案：<p role="alert"> min-w-0 + truncate + title 全文可达', () => {
    expect(entryList).toMatch(
      /<p\s+role="alert"\s+data-testid="batch-failed"\s+className="min-w-0 flex-1 truncate text-xs text-\[var\(--lumi-danger\)\]"\s+title=/,
    )
  })
})
