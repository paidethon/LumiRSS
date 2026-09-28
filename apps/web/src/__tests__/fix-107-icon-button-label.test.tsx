/**
 * FIX-107 — icon-only 按钮必须有可访问名称（source-level 守卫，与
 * FIX-089 的 input 守卫同型）。
 *
 * 审计结论（2026-09 R2）：全库 107 处 `<IconButton>` 用法全部带
 * label / aria-label（或文本 children），无存量违规；本文件把该结论
 * 钉成回归守卫。审计方法与盲区：
 * - 扫描 `<IconButton` 开标签（引号 + JSX 花括号深度感知提取，同 089）；
 * - 满足其一即合规：label= / aria-label= / aria-labelledby= 属性；
 *   或 children 含文本（字符串字面量 / CJK / 单标识符表达式——即
 *   primitive 注释允许的 visually-hidden 文本兜底）；
 * - 已知盲区（如实记录）：`{...rest}` 透传的 aria-label 无法静态识别
 *   （现库无此用法）；children 为复杂表达式时按其文本形态启发式判定。
 *
 * 另含运行时冒烟：IconButton 传 label → aria-label 落到 DOM（AC7）。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { IconButton } from '../components/ui/IconButton'

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

/** 引号 + JSX 花括号深度感知的标签提取（同 FIX-089）。 */
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

/** children 是否承载文本（可访问名的 children 兜底形态）。 */
function childrenCarryText(children: string): boolean {
  const trimmed = children.trim()
  if (trimmed.length === 0) return false
  // 剥掉 JSX 标签后：字符串字面量 / CJK 正文 / 文本型单标识符表达式
  const stripped = trimmed.replace(/<[^<>]*>/g, ' ')
  return (
    /["'`]/.test(stripped) ||
    /[\u4e00-\u9fff]/.test(stripped) ||
    /\{\s*[A-Za-z_$][\w$]*(\.[\w$]+)*\s*\}/.test(stripped)
  )
}

describe('FIX-107: 每处 IconButton 用法都有可访问名称来源', () => {
  it('label=/aria-label=/aria-labelledby= 或文本 children 三者必有其一', () => {
    const offenders: string[] = []
    for (const file of walk(srcRoot)) {
      const raw = readFileSync(file, 'utf-8')
      const rel = relative(srcRoot, file)
      const text = stripComments(raw)
      const re = /<IconButton\b/g
      let m: RegExpExecArray | null
      while ((m = re.exec(text)) !== null) {
        const tag = extractTag(text, m.index)
        if (
          /\blabel=/.test(tag) ||
          /\baria-label=/.test(tag) ||
          /\baria-labelledby=/.test(tag)
        ) {
          continue
        }
        const selfClosing = /\/>\s*$/.test(tag)
        let children = ''
        if (!selfClosing) {
          const closeIdx = text.indexOf('</IconButton>', m.index + tag.length)
          if (closeIdx !== -1) children = text.slice(m.index + tag.length, closeIdx)
        }
        if (childrenCarryText(children)) continue
        const line = raw.slice(0, m.index).split('\n').length
        offenders.push(`${rel}:${line} ${tag.slice(0, 140).replace(/\s+/g, ' ')}`)
      }
    }
    expect(offenders).toEqual([])
  })

  it('运行时冒烟：label 成为按钮的 aria-label（icon-only 控件 AC7）', () => {
    render(<IconButton icon={<span aria-hidden>i</span>} label="标记为已读" />)
    expect(screen.getByRole('button', { name: '标记为已读' })).toHaveAttribute(
      'aria-label',
      '标记为已读',
    )
  })
})
