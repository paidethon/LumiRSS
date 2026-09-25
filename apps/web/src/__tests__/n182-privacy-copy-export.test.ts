/** N182 隐私遮罩扩展到复制/导出文本测试。
 *
 * - 遮罩开启：剪贴板路径（引用复制 buildQuotePlainText/Markdown、代码
 *   块复制）与导出文件（buildMarkdownExport / buildHtmlExport）产出
 *   遮罩文本——原文绝不进入剪贴板/导出文件；
 * - 遮罩关闭：原样返回（零变化直通）。 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  buildQuoteMarkdownText,
  buildQuotePlainText,
} from '../lib/reader-tools'
import { buildHtmlExport, buildMarkdownExport } from '../lib/reader-export'
import { decorateCodeCopyButtons } from '../lib/code-copy'
import { maskPlainTextIfActive } from '../lib/privacy-mask'

const INPUT = {
  title: '机密文章标题',
  source: '某来源',
  url: 'https://example.com/a',
  text: '第一段敏感正文。\n\n第二段敏感正文。',
  html: '<p>第一段敏感正文。</p><p>第二段敏感正文。</p>',
  date: '2026-09-25',
}

function setMask(on: boolean) {
  if (on) localStorage.setItem('lumirss-privacy-demo', '1')
  else localStorage.removeItem('lumirss-privacy-demo')
}

afterEach(() => {
  setMask(false)
  vi.unstubAllGlobals()
})

describe('N182 遮罩开启时的复制路径', () => {
  it('maskPlainTextIfActive 替换为 ▮ 且不含原文', () => {
    setMask(true)
    const masked = maskPlainTextIfActive(INPUT.title)
    expect(masked).not.toContain('机密')
    expect(masked).toMatch(/^▮+$/)
    // CJK 按码点计数（8 字 → 8 个 ▮）。
    expect(masked).toHaveLength(6)
  })

  it('引用复制（纯文本/Markdown）输出遮罩文本', () => {
    setMask(true)
    const plain = buildQuotePlainText({ ...INPUT, quote: '选中的一段敏感文字' })
    expect(plain).not.toContain('机密文章标题')
    expect(plain).not.toContain('敏感文字')
    expect(plain).toMatch(/▮/)
    const markdown = buildQuoteMarkdownText({ ...INPUT, quote: '另一段敏感引文' })
    expect(markdown).not.toContain('机密文章标题')
    expect(markdown).not.toContain('敏感引文')
    expect(markdown).toMatch(/^▮+$/m)
  })

  it('代码块复制经遮罩写入剪贴板', async () => {
    document.body.innerHTML = ''
    const container = document.createElement('div')
    container.innerHTML = '<pre><code>const secret = "敏感令牌";</code></pre>'
    document.body.appendChild(container)
    setMask(true)
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
    expect(written[0]).not.toContain('敏感令牌')
    expect(written[0]).toMatch(/^▮+$/)
  })
})

describe('N182 遮罩开启时的导出路径', () => {
  it('Markdown 导出文件遮罩（标题/正文无原文）', () => {
    setMask(true)
    const markdown = buildMarkdownExport(INPUT)
    expect(markdown).not.toContain('机密文章标题')
    expect(markdown).not.toContain('敏感正文')
    expect(markdown).toMatch(/^# ▮+$/m)
  })

  it('HTML 导出遮罩：不携带未遮罩 HTML 传输层', () => {
    setMask(true)
    const html = buildHtmlExport(INPUT)
    expect(html).not.toContain('机密文章标题')
    expect(html).not.toContain('敏感正文')
    expect(html).toContain('▮')
  })
})

describe('N182 遮罩关闭时原样直通', () => {
  it('复制与导出均保持原文', () => {
    setMask(false)
    expect(maskPlainTextIfActive(INPUT.title)).toBe(INPUT.title)
    const plain = buildQuotePlainText({ ...INPUT, quote: '普通引用' })
    expect(plain).toContain('机密文章标题')
    expect(plain).toContain('普通引用')
    const markdown = buildMarkdownExport(INPUT)
    expect(markdown).toContain('机密文章标题')
    expect(markdown).toContain('敏感正文')
    const html = buildHtmlExport(INPUT)
    expect(html).toContain('敏感正文') // html 传输层原样
  })

  it('空文本直通（遮罩开启时也不产生 1 个 ▮）', () => {
    setMask(true)
    expect(maskPlainTextIfActive('')).toBe('')
  })
})
