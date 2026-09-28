/**
 * FIX-135 — 字体与行宽设置只作用于普通段落、不作用于列表或引用块。
 *
 * 审计结论（2026-09 R2，feat/r2-web9 @1b7f54e）：现行实现不存在该缺陷
 * ——排版变量挂在 .article-content【容器】上：
 * - font-size / line-height：容器级声明，li / blockquote / table 文本
 *   经继承生效；正文内所有字号覆盖（h1–h6、pre、code、figcaption）
 *   一律是 em 相对值（相对继承的 reader 字号缩放），没有任何绝对值
 *   覆盖把列表/引用打回默认字号；
 * - 行宽：--lumi-reader-content-width 挂在 .lumi-reader-article
 *   max-width 上（Reader.tsx），列表/引用/表格同在列宽约束内；
 * - store 侧 readerTypographyVars 把 readerFontSize / readerLineHeight /
 *   readerContentWidth 逐一映射为 --lumi-reader-* 变量。
 * 本测试把这些结构固化为 source 断言（jsdom 无布局，CSS 继承不可计算）。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const srcRoot = resolve(__dirname, '..')
const css = readFileSync(resolve(srcRoot, 'index.css'), 'utf-8')
const storeSrc = readFileSync(resolve(srcRoot, 'store/app-settings.ts'), 'utf-8')
const readerSrc = readFileSync(resolve(srcRoot, 'components/Reader.tsx'), 'utf-8')

/** 从 CSS 文本里取出 selector 首次出现到配对 `}` 的完整块（支持块内无嵌套）。 */
function cssBlock(selector: string): string | null {
  const idx = css.indexOf(selector)
  if (idx === -1) return null
  const open = css.indexOf('{', idx)
  const close = css.indexOf('}', open)
  if (open === -1 || close === -1) return null
  return css.slice(open + 1, close)
}

/** 移除平衡的 @media print 块（打印排版是独立媒体场景，不在本断言范围）。 */
function stripPrintMedia(source: string): string {
  const start = source.indexOf('@media print')
  if (start === -1) return source
  const open = source.indexOf('{', start)
  let depth = 0
  for (let i = open; i < source.length; i++) {
    if (source[i] === '{') depth++
    else if (source[i] === '}') {
      depth--
      if (depth === 0) return source.slice(0, start) + source.slice(i + 1)
    }
  }
  return source
}

/** 收集 .article-content 作用域内所有 font-size 声明（selector, value）。 */
function articleFontSizes(cssText: string): Array<{ selector: string; value: string }> {
  const out: Array<{ selector: string; value: string }> = []
  for (const m of cssText.matchAll(/(^|\n)(\.article-content[^{\n]*)\{([^}]*)\}/g)) {
    const selector = m[2]!.trim()
    for (const v of m[3]!.matchAll(/font-size:\s*([^;]+);/g)) {
      out.push({ selector, value: v[1]!.trim() })
    }
  }
  return out
}

/** 正文流 UI 控件（复制/展开/段落链接按钮等 chrome）——固定字号是
 * 刻意的，不属于「内容文本」作用域断言。 */
const CONTROL_SELECTORS = [
  'code-copy-btn',
  'lumi-table-expand-btn',
  'lumi-code-expand-btn',
  'lumi-para-link',
]

describe('FIX-135: 阅读排版变量挂在容器上（列表/引用块继承生效）', () => {
  it('.article-content 容器声明 font-size/line-height（非 p 级作用域）', () => {
    const block = cssBlock('.article-content {')
    expect(block).not.toBeNull()
    expect(block).toContain('font-size: var(--lumi-reader-font-size')
    expect(block).toContain('line-height: var(--lumi-reader-line-height')
  })

  it('排版不降级为段落作用域：.article-content p 规则不含 font-size/line-height', () => {
    const block = cssBlock('.article-content p {')
    expect(block).not.toBeNull()
    expect(block).not.toContain('font-size')
    expect(block).not.toContain('line-height')
  })

  it('正文文本的所有 font-size 覆盖都是相对值（em），无绝对值覆盖列表/引用', () => {
    const screenCss = stripPrintMedia(css)
    const declarations = articleFontSizes(screenCss).filter(
      ({ selector }) => !CONTROL_SELECTORS.some((c) => selector.includes(c)),
    )
    // 容器声明（var + rem 回退值）+ 内容元素 em 缩放。
    expect(declarations.length).toBeGreaterThan(0)
    const offenders = declarations.filter(
      ({ value }) => !value.startsWith('var(') && !value.endsWith('em'),
    )
    expect(offenders).toEqual([])
  })

  it('li / blockquote / table 无字号/行高覆盖（保持继承）', () => {
    for (const selector of ['.article-content li {', '.article-content blockquote {']) {
      const block = cssBlock(selector)
      expect(block).not.toBeNull()
      expect(block).not.toContain('font-size')
      expect(block).not.toContain('line-height')
    }
    // table 单元格同样只调间距，不覆盖排版继承。
    const th = cssBlock('.article-content th,')
    expect(th).not.toBeNull()
    expect(th).not.toContain('font-size')
  })

  it('行宽作用于整个 article 列（列表/引用同宽约束）', () => {
    expect(readerSrc).toContain("maxWidth: 'var(--lumi-reader-content-width")
    const article = cssBlock('.lumi-reader-article {')
    expect(article).not.toBeNull()
  })

  it('store 把字号/行高/行宽设置映射为 --lumi-reader-* 变量', () => {
    expect(storeSrc).toContain("'--lumi-reader-font-size'")
    expect(storeSrc).toContain("'--lumi-reader-line-height'")
    expect(storeSrc).toContain("'--lumi-reader-content-width'")
  })
})
