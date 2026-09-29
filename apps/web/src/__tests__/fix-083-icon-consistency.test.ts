/**
 * FIX-083 — 图标视觉重量统一：描边、基线与默认尺寸。
 *
 * 审计结论（2026-09 R2 基线）：全库图标统一来自 lucide-react（默认
 * strokeWidth=2、24 栅格基线），尺寸一律 `size-*` 工具类；唯一的
 * `strokeWidth` 覆盖在 MobilePageHeader 的自定义汉堡 SVG（原生 <path>，
 * 非图标组件）。守卫钉定：
 *   1. `strokeWidth` 只允许出现在原生 SVG 原语标签上（path/circle/
 *      line/rect/polyline/polygon），绝不允许覆盖 lucide 组件描边；
 *   2. 不使用 lucide 的 absoluteStrokeWidth 覆盖。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const srcRoot = resolve(__dirname, '..')

const SVG_PRIMITIVES = new Set(['path', 'circle', 'line', 'rect', 'polyline', 'polygon', 'ellipse'])

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

describe('FIX-083: 图标描边统一（lucide 默认 strokeWidth，不逐处覆盖）', () => {
  it('strokeWidth 只出现在原生 SVG 原语上，且无 absoluteStrokeWidth', () => {
    const offenders: string[] = []
    for (const file of walk(srcRoot)) {
      const raw = readFileSync(file, 'utf-8')
      const rel = relative(srcRoot, file)
      if (raw.includes('absoluteStrokeWidth')) offenders.push(`${rel}: absoluteStrokeWidth`)
      for (const m of raw.matchAll(/strokeWidth=/g)) {
        const open = raw.lastIndexOf('<', m.index)
        const tag = extractTag(raw, open)
        const tagName = /^<([A-Za-z][\w.]*)/.exec(tag)?.[1] ?? ''
        if (!SVG_PRIMITIVES.has(tagName)) {
          const line = raw.slice(0, m.index).split('\n').length
          offenders.push(`${rel}:${line} <${tagName} strokeWidth…>`)
        }
      }
    }
    expect(offenders).toEqual([])
  })

  it('行为锚点：MobilePageHeader 汉堡线为唯一描边覆盖（原生 path 1.6）', () => {
    const header = readFileSync(resolve(srcRoot, 'components/MobilePageHeader.tsx'), 'utf-8')
    expect(header).toContain('<path d="M2 4h14M2 9h14M2 14h14" stroke="currentColor" strokeWidth="1.6"')
  })
})
