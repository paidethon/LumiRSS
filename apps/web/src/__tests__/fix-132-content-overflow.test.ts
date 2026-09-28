/**
 * FIX-132 — 宽表格 / 代码块 / 公式撑破阅读面板。
 *
 * 语义：三类潜在超宽内容都在「自己的容器内」横向滚动，永不把阅读列
 * 或整页拖宽：
 * - 表格：.article-content table display:block + overflow-x:auto +
 *   max-width:100%（index.css；jsdom 无布局，绑定 source 断言）；
 * - 代码块：.article-content pre overflow-x:auto（index.css）；
 * - 公式：KaTeX 自带样式只有 white-space:nowrap，超宽 display 公式
 *   无溢出处理——index.css 以 .article-content .katex-display
 *   overflow-x:auto + max-width:100% 收进自身容器；
 * - 祖先防御：.lumi-reader min-width:0（高亮 code min-content 超宽时
 *   不撑破 grid 祖先）。
 * 管线侧断言：display 公式渲染产物确实带 .katex-display（CSS 规则的
 * 命中对象存在，两类断言闭合）。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { renderArticleHtml } from '../lib/article-pipeline'

const srcRoot = resolve(__dirname, '..')
const css = readFileSync(resolve(srcRoot, 'index.css'), 'utf-8')

/** 取行首锚定的 selector 的 CSS 块体（避免命中注释/更长选择器子串）。 */
function cssBlock(selector: string): string | null {
  const idx = css.indexOf(`\n${selector}`)
  if (idx === -1) return null
  const open = css.indexOf('{', idx)
  const close = css.indexOf('}', open)
  if (open === -1 || close === -1) return null
  return css.slice(open + 1, close)
}

describe('FIX-132: 宽内容在自身容器内滚动', () => {
  it('宽表格：display:block + overflow-x:auto + max-width:100%', () => {
    const block = cssBlock('.article-content table')
    expect(block).not.toBeNull()
    expect(block).toContain('display: block')
    expect(block).toContain('overflow-x: auto')
    expect(block).toContain('max-width: 100%')
  })

  it('代码块：pre overflow-x:auto（横向滚动不外溢）', () => {
    const block = cssBlock('.article-content pre')
    expect(block).not.toBeNull()
    expect(block).toContain('overflow-x: auto')
  })

  it('公式（FIX-132 本体）：katex-display 收进自身容器滚动', () => {
    const block = cssBlock('.article-content .katex-display')
    expect(block).not.toBeNull()
    expect(block).toContain('overflow-x: auto')
    expect(block).toContain('max-width: 100%')
  })

  it('祖先防御：.lumi-reader min-width:0（不撑破 grid 布局）', () => {
    const block = cssBlock('.lumi-reader')
    expect(block).not.toBeNull()
    expect(block).toContain('min-width: 0')
  })

  it('管线产物命中 CSS 对象：display 公式带 .katex-display（可滚动容器存在）', async () => {
    const out = await renderArticleHtml('<p>$$x_{1}+\\cdots+x_{n}$$</p>', {
      conversion: 'off',
      bionic: false,
      codeTheme: null,
      math: true,
    })
    expect(out).toContain('katex-display')
    // 公式同样过最终安全边界。
    expect(out).not.toMatch(/<script/i)
  })
})
