/** N182 后继 —— 导出/复制路径不再依赖「演示隐私遮罩」。
 *
 * F113 演示隐私遮罩（DOM 文本替换 + 剪贴板/导出文本改写）已移除：
 * 1. 静态：reader-export / reader-tools / code-copy 源码零
 *    privacy-mask 引用（防回归：任何路径重新引入遮罩改写即失败）；
 * 2. 行为：导出与剪贴板输出原文直通，不出现 ▮ 遮罩块；HTML 导出
 *    原样携带 html 传输层（script 标签仍由 stripScriptTags 剥离）。
 * 真隐私与安全能力不受影响（远程图片控制、数据驻留、日志脱敏、
 * 密钥掩码均属 BFF 侧，见 routers/privacy.py）。 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { buildQuoteMarkdownText, buildQuotePlainText } from '../lib/reader-tools'
import { buildHtmlExport, buildMarkdownExport, stripScriptTags } from '../lib/reader-export'
import { decorateCodeCopyButtons } from '../lib/code-copy'

const read = (rel: string): string =>
  readFileSync(resolve(__dirname, '..', rel), 'utf-8')

const INPUT = {
  title: '普通文章标题',
  source: '某来源',
  url: 'https://example.com/a',
  text: '第一段正文。\n\n第二段正文。',
  html: '<p>第一段正文。</p><script>alert(1)</script><p>第二段正文。</p>',
  date: '2026-10-02',
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('N182: 导出/复制路径无演示遮罩依赖', () => {
  it('静态：导出/引用/代码复制源码零 privacy-mask 引用', () => {
    for (const rel of ['lib/reader-export.ts', 'lib/reader-tools.ts', 'lib/code-copy.ts']) {
      const source = read(rel)
      expect(source, rel).not.toContain('privacy-mask')
      expect(source, rel).not.toContain('maskPlainTextIfActive')
      expect(source, rel).not.toContain('lumirss-privacy-demo')
      expect(source, rel).not.toContain('data-privacy-text')
    }
  })

  it('行为：导出原文直通，不含 ▮ 遮罩块；HTML 传输层保留且剥离 script', () => {
    const markdown = buildMarkdownExport(INPUT)
    expect(markdown).toContain('# 普通文章标题')
    expect(markdown).toContain('第一段正文。')
    expect(markdown).not.toMatch(/▮/)

    const html = buildHtmlExport(INPUT)
    expect(html).toContain('<title>普通文章标题</title>')
    expect(html).toContain('第一段正文。') // html 传输层原样保留
    expect(html).not.toContain('<script') // stripScriptTags 边界仍在
    expect(html).not.toMatch(/▮/)

    const quote = buildQuotePlainText({ ...INPUT, quote: '一段引用' })
    expect(quote).toContain('普通文章标题')
    expect(quote).toContain('一段引用')
    const quoteMd = buildQuoteMarkdownText({ ...INPUT, quote: '一段引用' })
    expect(quoteMd).toContain('> 一段引用')
    expect(quoteMd).not.toMatch(/▮/)
  })

  it('行为：代码块复制直通原文（无遮罩改写）', async () => {
    document.body.innerHTML = ''
    const container = document.createElement('div')
    container.innerHTML = '<pre><code>const value = "token-123";</code></pre>'
    document.body.appendChild(container)
    const written: string[] = []
    decorateCodeCopyButtons(container, {
      writeText: async (text) => {
        written.push(text)
      },
    })
    const button = container.querySelector<HTMLButtonElement>('.code-copy-btn')
    expect(button).not.toBeNull()
    button!.click()
    await vi.waitFor(() => expect(written).toHaveLength(1))
    expect(written[0]).toContain('token-123')
    expect(written[0]).not.toMatch(/▮/)
  })

  it('stripScriptTags 独立边界：成对与未闭合 script 均剥离', () => {
    expect(stripScriptTags('<p>a</p><script>x()</script><p>b</p>')).toBe('<p>a</p><p>b</p>')
    expect(stripScriptTags('<p>a</p><script src="https://evil.example/x.js">')).toBe('<p>a</p>')
  })
})
