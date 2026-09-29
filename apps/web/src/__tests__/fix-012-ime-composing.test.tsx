/**
 * FIX-012 — 中文输入法组合输入时 Enter 不得误触发提交类动作。
 *
 * 缺陷：多个面板的 `onKeyDown` Enter 处理只判 `e.key === 'Enter'`。
 * 组合输入（拼音/注音）期间按 Enter 是「确认候选词上屏」，浏览器在该
 * 次按键上置 `isComposing=true`（老引擎 keyCode=229）——原实现会把
 * 上屏确认当成用户提交：中文命名篮子时提前建篮、中文输入搜索词时
 * 提前触发搜索/重命名/复跑。
 *
 * 修复：全部提交类 Enter 处理加 `!e.nativeEvent.isComposing`（与
 * ArticleConversation 既有写法一致；CommandPalette / ReaderKeyNav 走
 * 共享 `shouldIgnoreKeyEvent` 守卫，本就正确，一并钉定）。
 *
 * 守卫（source-level）：扫描全部 tsx 的内联 `onKeyDown={(…) => {…}}`
 * 函数体，凡引用 `key === 'Enter'` 必须同处出现 `isComposing`；
 * named handler（onInputKeyDown）单独断言其 IME 守卫仍在。
 * 例外清单（并发批次拥有的模块，本轮不动，如实记录）：
 * ObsidianPage（obsidian）、AgentWorkbenchPage（agent/AI）、
 * KnowledgeCardsManager（知识卡片/AI 邻接）。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { FilterRulesSection } from '../components/settings/FilterRulesPage'
import { useAppSettings, DEFAULT_APP_SETTINGS } from '../store/app-settings'

const srcRoot = resolve(__dirname, '..')

/** 并发批次拥有的模块（本轮豁免；后续批次收口）。 */
const OWNED_EXEMPTIONS = new Set([
  'components/pages/ObsidianPage.tsx',
  'components/pages/AgentWorkbenchPage.tsx',
  'components/KnowledgeCardsManager.tsx',
])

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

function stripComments(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/^\s*\/\/.*$/gm, '')
}

/** 从 openBrace 起做引号感知的花括号配对，返回函数体内部文本。 */
function extractBraceBody(text: string, openBrace: number): string {
  let depth = 0
  let quote: string | null = null
  for (let i = openBrace; i < text.length; i += 1) {
    const ch = text[i]
    if (quote !== null) {
      if (ch === '\\') {
        i += 1
      } else if (ch === quote) {
        quote = null
      }
    } else if (ch === '"' || ch === "'" || ch === '`') {
      quote = ch
    } else if (ch === '{') {
      depth += 1
    } else if (ch === '}') {
      depth -= 1
      if (depth === 0) return text.slice(openBrace + 1, i)
    }
  }
  return text.slice(openBrace + 1)
}

describe('FIX-012: 提交类 Enter 处理必须尊重输入法组合态', () => {
  it('source 守卫：内联 onKeyDown 体内 key === Enter 处必须出现 isComposing', () => {
    const offenders: string[] = []
    for (const file of walk(srcRoot)) {
      const rel = relative(srcRoot, file)
      if (OWNED_EXEMPTIONS.has(rel)) continue
      const text = stripComments(readFileSync(file, 'utf-8'))
      for (const m of text.matchAll(/onKeyDown=\{\s*\(\s*\w+\s*\)\s*=>\s*\{/g)) {
        const body = extractBraceBody(text, m.index + m[0].length - 1)
        if (/key === ['"]Enter['"]/.test(body) && !body.includes('isComposing')) {
          const line = text.slice(0, m.index).split('\n').length
          offenders.push(`${rel}:${line}`)
        }
      }
    }
    expect(offenders).toEqual([])
  })

  it('CommandPalette 的 named onInputKeyDown 仍走共享 IME 守卫（shouldIgnoreKeyEvent）', () => {
    const text = readFileSync(resolve(srcRoot, 'components/CommandPalette.tsx'), 'utf-8')
    expect(text).toContain('shouldIgnoreKeyEvent(event.nativeEvent)')
    // ReaderKeyNav（window 级 Enter/方向键）同源守卫。
    const keynav = readFileSync(resolve(srcRoot, 'lib/reader-keynav.ts'), 'utf-8')
    expect(keynav).toContain('shouldIgnoreKeyEvent(e)')
  })

  it('自查：花括号提取器不会被箭头函数体 / 模板字面量欺骗', () => {
    const snippet = 'onKeyDown={(e) => { if (e.key === "Enter" && !e.nativeEvent.isComposing) { run(`a{b}`) } }}'
    const m = /onKeyDown=\{\s*\(\s*\w+\s*\)\s*=>\s*\{/.exec(snippet)
    expect(m).not.toBeNull()
    const body = extractBraceBody(snippet, m!.index + m![0].length - 1)
    expect(body).toContain('isComposing')
    expect(body).toContain('run(')
  })
})

describe('FIX-012 运行时：组合态 Enter 不加规则，非组合 Enter 正常加', () => {
  beforeEach(() => {
    useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
  })

  it('FilterRulesSection：isComposing Enter 仅上屏候选词；随后的普通 Enter 才添加规则', () => {
    render(<FilterRulesSection />)
    fireEvent.click(screen.getByRole('button', { name: '添加过滤规则' }))
    const input = screen.getByLabelText('规则内容')
    fireEvent.change(input, { target: { value: '广告' } })

    // 输入法组合中的 Enter（确认候选词）→ 不添加规则，对话框保持打开。
    fireEvent.keyDown(input, { key: 'Enter', isComposing: true })
    expect(useAppSettings.getState().settings.filterRules).toHaveLength(0)
    expect(screen.getByLabelText('规则内容')).toBeTruthy()

    // 组合结束后（isComposing 缺省 false）的 Enter → 正常添加并关闭。
    fireEvent.keyDown(input, { key: 'Enter' })
    const rules = useAppSettings.getState().settings.filterRules
    expect(rules).toHaveLength(1)
    expect(rules[0]?.keyword).toBe('广告')
    expect(screen.queryByLabelText('规则内容')).toBeNull()
  })
})
