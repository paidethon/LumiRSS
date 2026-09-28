/**
 * FIX-089 — 占位符不得作为唯一的字段标签（source-level 可访问性守卫）。
 *
 * 审计结论（2026-09 R2）：全库不存在「placeholder 是唯一标签」的输入——
 * 所有带 placeholder 的控件均有可见 <label>（htmlFor 或包裹）或 aria-label。
 * 守卫同时覆盖更广的「控件无可编程标签」类：修复了 4 处 sr-only 文件导入
 * input（type=file + sr-only，触发按钮有文案但控件本身无可编程名）。
 *
 * 方法：扫描全部 input / textarea / select 原始标签（引号 + JSX 花括号
 * 深度感知的标签提取，剥离注释后匹配），判定每个控件是否有可编程关联的
 * 标签，满足其一即可：
 *   1. aria-label / aria-labelledby；
 *   2. id + 本文件内 htmlFor 配对（模板字面量归一化后精确配对）；
 *   3. 源码上被 <label>…</label> 包裹（隐式关联）。
 *
 * 已知盲区（如实记录）：经 ui/Select、ui/Slider 等原语转发的控件按原语
 * 定义扫描（原语透传 aria 属性，具体用法的标签性由调用方保证）；本扫描
 * 不覆盖 `<Select …>` 这类大写开头的组件调用点。
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

/** 引号 + JSX 花括号深度感知的标签提取：'>' 仅在引号外且花括号深度 0 时
 * 结束标签（属性值里的箭头函数 `=> { … }`、模板字面量不会误断）。 */
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

function attrValue(tag: string, attr: string): string | null {
  const m = tag.match(
    new RegExp(`\\b${attr}=(?:"([^"]*)"|'([^']*)'|\\{([\\s\\S]*?)\\})(?=\\s|/?>|$)`),
  )
  if (!m) return null
  return (m[1] ?? m[2] ?? m[3] ?? '').trim()
}

/** 位置 pos 是否被 <label …> 包裹（pos 前最近的 <label 未被 </label> 闭合）。 */
function insideWrappingLabel(text: string, pos: number): boolean {
  const open = text.lastIndexOf('<label', pos)
  if (open === -1) return false
  const close = text.lastIndexOf('</label>', pos)
  return close < open
}

/** 归一化表达式用于 id ↔ htmlFor 配对：去掉引号/反引号/花括号/空白。 */
function normalizeExpr(expr: string): string {
  return expr.replace(/["'`{}\s]/g, '')
}

function stripComments(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/^\s*\/\/.*$/gm, '')
}

describe('FIX-089: 表单控件都有 placeholder 之外的可编程标签', () => {
  // 原语透传 aria 属性（...rest），可访问名由调用方提供；这里扫的是
  // 原始标签用法，原语定义本身不是违规（见文件头「已知盲区」）。
  const PRIMITIVE_DEFINITIONS = new Set(['components/ui/Select.tsx'])

  it('每个 input/textarea/select 具备 aria-label、id+htmlFor 或包裹 label', () => {
    const offenders: string[] = []
    for (const file of walk(srcRoot)) {
      const raw = readFileSync(file, 'utf-8')
      const rel = relative(srcRoot, file)
      if (PRIMITIVE_DEFINITIONS.has(rel)) continue
      const text = stripComments(raw)
      const htmlForPairs = new Set<string>()
      for (const m of text.matchAll(
        /htmlFor=(?:"([^"]*)"|'([^']*)'|\{([^}]*)\})/g,
      )) {
        htmlForPairs.add(normalizeExpr(m[1] ?? m[2] ?? m[3] ?? ''))
      }
      for (const m of text.matchAll(/<(input|textarea|select)\b/g)) {
        const tag = extractTag(text, m.index)
        if (attrValue(tag, 'aria-label') !== null) continue
        if (attrValue(tag, 'aria-labelledby') !== null) continue
        if (insideWrappingLabel(text, m.index)) continue
        const id = attrValue(tag, 'id')
        if (id !== null && htmlForPairs.has(normalizeExpr(id))) continue
        const line = raw.slice(0, m.index ?? 0).split('\n').length
        offenders.push(`${rel}:${line} ${tag.slice(0, 140).replace(/\s+/g, ' ')}`)
      }
    }
    expect(offenders).toEqual([])
  })

  it('自查：JSX 箭头函数 / 模板字面量 id 不会被标签提取误断', () => {
    const entryCard = readFileSync(
      resolve(srcRoot, 'components/EntryCard.tsx'),
      'utf-8',
    )
    const m = /<input\b/.exec(entryCard)
    expect(m).not.toBeNull()
    const tag = extractTag(entryCard, m?.index ?? 0)
    // 完整取到 aria-label（在 onChange 箭头函数之后）
    expect(tag).toContain('aria-label=')
    expect(tag).toContain('stopPropagation')
    // 模板字面量 id ↔ htmlFor 归一化配对
    expect(normalizeExpr('`add-source-rsshub-param-${parameter.key}`')).toBe(
      normalizeExpr('{`add-source-rsshub-param-${parameter.key}`}'),
    )
  })
})
