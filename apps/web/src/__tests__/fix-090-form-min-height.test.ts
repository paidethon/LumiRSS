/**
 * FIX-090（部分）— 200% 缩放/系统大字体下表单控件文本不裁切。
 *
 * 审计结论（2026-09 R2）：交互控件高度约定是 `min-h-*`（内容可撑高），
 * 但仍有 8 处表单控件用固定 `h-7/h-8/h-9/h-11`——大字号下文本被裁切。
 * 本轮全部改为 `min-h-*`（单行内容下视觉等价，大字号可撑高）。
 * 守卫：全库 input/select/textarea 的 className 不得出现裸 `h-N`
 * 固定高度（无配套 min-h）。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const srcRoot = resolve(__dirname, '..')

function walk(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    const st = statSync(p)
    if (st.isDirectory()) {
      if (name === '__tests__' || name === 'generated') continue
      out.push(...walk(p))
    } else if (/\.tsx$/.test(name)) {
      out.push(p)
    }
  }
  return out
}

/** 引号 + 花括号深度感知的标签提取（同 fix-089 手法）。 */
function extractTag(text: string, start: number): string {
  let i = start
  let quote: string | null = null
  let depth = 0
  while (i < text.length) {
    const ch = text[i]
    if (quote !== null) {
      if (ch === quote) quote = null
    } else if (ch === '"' || ch === "'" || ch === '`') {
      quote = ch
    } else if (ch === '{') {
      depth += 1
    } else if (ch === '}') {
      depth = Math.max(0, depth - 1)
    } else if (ch === '>' && depth === 0) {
      return text.slice(start, i + 1)
    }
    i += 1
  }
  return text.slice(start)
}

function stripComments(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/^\s*\/\/.*$/gm, '')
}

describe('FIX-090: 表单控件不使用固定高度（200% 缩放可撑高）', () => {
  it('input/select/textarea 的 className 无裸 h-N（必须 min-h-N）', () => {
    const offenders: string[] = []
    for (const file of walk(srcRoot)) {
      const raw = readFileSync(file, 'utf-8')
      const rel = relative(srcRoot, file)
      const text = stripComments(raw)
      for (const m of text.matchAll(/<(input|textarea|select)\b/g)) {
        const tag = extractTag(text, m.index)
        const cls = /className=\{?[`"']([^`"']*)/.exec(tag)?.[1] ?? ''
        if (cls === '') continue
        const tokens = cls.split(/\s+/)
        const fixed = tokens.filter((t) => /^h-\d+(?![\d-])/.test(t))
        if (fixed.length > 0 && !tokens.some((t) => t.startsWith('min-h-'))) {
          const line = raw.slice(0, m.index ?? 0).split('\n').length
          offenders.push(`${rel}:${line} ${fixed.join(' ')}`)
        }
      }
    }
    expect(offenders).toEqual([])
  })

  it('本轮修复的锚点：宽表筛选、代码搜索、别名词典输入都是 min-h', () => {
    const expectations: Array<[string, RegExp]> = [
      ['components/WideTablePanel.tsx', /min-h-7 w-14/],
      ['components/CodeReaderPanel.tsx', /min-h-8 w-36/],
      ['components/SourceAliasDialog.tsx', /min-h-11 min-w-0 flex-1/],
      ['components/SourceAliasSettings.tsx', /min-h-11 min-w-0 basis-40/],
      ['components/ReaderHeader.tsx', /min-h-9 min-w-0 flex-1/],
      ['components/settings/DictSourceSettings.tsx', /min-h-9 min-w-0 flex-1/],
    ]
    for (const [file, pattern] of expectations) {
      expect(readFileSync(resolve(srcRoot, file), 'utf-8'), file).toMatch(pattern)
    }
  })
})
