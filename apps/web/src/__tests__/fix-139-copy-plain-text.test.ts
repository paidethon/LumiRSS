/** FIX-139 — 代码复制 / 引用复制：剪贴板是解码后的纯文本。
 *
 * - 代码块复制（lib/code-copy）：复制源取 <pre><code> 的 textContent
 *   ——HTML 解析天然解码实体（&amp;→&、&lt;→<），缩进与内部换行原样
 *   保留，仅结尾换行剥离；
 * - 引用复制（lib/reader-tools buildQuotePlainText / buildQuoteMarkdownText）：
 *   输入来自 window.getSelection().toString()（浏览器已解码），本套件
 *   锁定纯函数行为——含 & < > 的引文逐字透传、多行换行精确保留，绝不
 *   出现实体残留或换行损坏。
 */

import { describe, expect, it, vi } from 'vitest'
import { codeBlockText, decorateCodeCopyButtons } from '../lib/code-copy'
import {
  buildQuoteMarkdownText,
  buildQuotePlainText,
} from '../lib/reader-tools'

function mount(html: string): HTMLElement {
  const container = document.createElement('div')
  container.innerHTML = html
  document.body.appendChild(container)
  return container
}

describe('codeBlockText：实体解码 + 换行/缩进保真', () => {
  it('实体源码解码为真实字符（& < > " \'），不残留 &amp;/&lt;', () => {
    const container = mount(
      '<pre><code>if (a &amp;&amp; b) {\n  echo "&lt;tag&gt; &amp; &#39;q&#39;";\n}</code></pre>',
    )
    expect(codeBlockText(container.querySelector('pre')!)).toBe(
      'if (a && b) {\n  echo "<tag> & \'q\'";\n}',
    )
    container.remove()
  })

  it('多行 + 空行 + 缩进逐字保留，仅剥离结尾换行', () => {
    const container = mount(
      '<pre><code>def f():\n    x = 1\n\n    return f"&lt;{x}&gt;"\n</code></pre>',
    )
    expect(codeBlockText(container.querySelector('pre')!)).toBe(
      'def f():\n    x = 1\n\n    return f"<{x}>"',
    )
    container.remove()
  })

  it('复制按钮写入剪贴板的即解码文本（DOM 装饰端到端）', async () => {
    const writes: string[] = []
    const container = mount(
      '<pre><code>const s = "&amp;" + "&lt;div&gt;";\nrun(s);\n</code></pre>',
    )
    decorateCodeCopyButtons(container, {
      writeText: async (text) => {
        writes.push(text)
      },
      scheduleRevert: (fn) => fn(),
    })
    const button = container.querySelector('.code-copy-btn') as HTMLButtonElement
    button.click()
    await vi.waitFor(() =>
      expect(writes).toEqual(['const s = "&" + "<div>";\nrun(s);']),
    )
    expect(writes[0]).not.toContain('&amp;')
    expect(writes[0]).not.toContain('&lt;')
    container.remove()
  })

  it('无 <code> 的裸 <pre> 同样解码', () => {
    const container = mount('<pre>a &amp; b\nc &lt;d&gt;</pre>')
    expect(codeBlockText(container.querySelector('pre')!)).toBe('a & b\nc <d>')
    container.remove()
  })
})

describe('buildQuotePlainText / buildQuoteMarkdownText：引文逐字透传', () => {
  it('含 & < > 的引文不编码（无实体残留），换行精确保留', () => {
    const quote = '第一行 A & B\n第二行 <b>加粗</b> &amp; 已是解码文本\n\n第四行'
    const text = buildQuotePlainText({
      title: '标题 & 子题',
      source: '某来源',
      url: 'https://example.com/a',
      quote,
    })
    expect(text).toBe(
      '标题 & 子题\n某来源\nhttps://example.com/a\n\n第一行 A & B\n第二行 <b>加粗</b> &amp; 已是解码文本\n\n第四行',
    )
    expect(text).not.toContain('&amp;amp;')
  })

  it('Markdown 格式同样逐字透传引文与换行', () => {
    const quote = 'x & y\nz <w>'
    const text = buildQuoteMarkdownText({
      title: 'T',
      source: 'S',
      url: null,
      quote,
    })
    expect(text).toBe('T\nS\n\n> x & y\nz <w>')
  })

  it('引文两端空白被裁剪（不产生空首行），中间结构不动', () => {
    const text = buildQuotePlainText({
      title: 'T',
      source: 'S',
      url: null,
      quote: '  a\n  b  ',
    })
    expect(text).toBe('T\nS\n\na\n  b')
  })
})
