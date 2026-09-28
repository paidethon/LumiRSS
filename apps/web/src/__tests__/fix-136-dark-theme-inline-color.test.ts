/**
 * FIX-136 — 深色主题下原文内联颜色破坏可读性。
 *
 * 边界语义（sanitize-article-html.ts）：
 * - 作者 inline style（style 属性）一律移除；
 * - 表现层颜色属性（font color / bgcolor / background 属性）与 style
 *   同罪，一并移除（HTML profile 默认放行它们，是深色主题下
 *   `color="#333"` / `bgcolor="white"` 不可读区块的漏口）；
 * - 保留图片（img 元素与 src）；
 * - 保留 class 承载的语义色（shiki 代码高亮 `.lumi-sh-*`——颜色来自
 *   运行时样式表、随明暗主题切换，是「必要语义」）。
 */

import { describe, expect, it } from 'vitest'
import { renderArticleHtml } from '../lib/article-pipeline'
import { sanitizeArticleHtml } from '../lib/sanitize-article-html'

function parseDom(html: string): HTMLElement {
  const container = document.createElement('div')
  container.innerHTML = html
  return container
}

describe('FIX-136: 内联颜色在 sanitize 边界中和', () => {
  it('style 属性移除（作者 color/background 不进 Reader）', () => {
    const out = sanitizeArticleHtml(
      '<p><span style="color:#eee;background:#111">浅灰字黑底</span>后续</p>',
    )
    const dom = parseDom(out)
    expect(dom.querySelector('span')?.getAttribute('style')).toBeNull()
    expect(dom.querySelector('span')?.textContent).toBe('浅灰字黑底')
    expect(out).not.toMatch(/\bstyle\s*=/i)
  })

  it('font color 属性移除（深色主题下 #333 文本不再不可读）', () => {
    const out = sanitizeArticleHtml('<p><font color="#333">深灰提示</font></p>')
    const dom = parseDom(out)
    const font = dom.querySelector('font')
    expect(font?.getAttribute('color')).toBeNull()
    // 文本内容保留（不因颜色中和丢内容）。
    expect(dom.textContent).toContain('深灰提示')
  })

  it('bgcolor 属性移除（白色色块不再出现在深色主题）', () => {
    const out = sanitizeArticleHtml(
      '<table><tr><td bgcolor="white">单元格</td></tr></table>',
    )
    const dom = parseDom(out)
    const td = dom.querySelector('td')
    expect(td?.getAttribute('bgcolor')).toBeNull()
    expect(td?.textContent).toBe('单元格')
  })

  it('background 属性移除（属性形态背景图不加载）', () => {
    const out = sanitizeArticleHtml(
      '<div background="https://evil.example/bg.png">内容</div>',
    )
    expect(out).not.toMatch(/\bbackground\s*=/i)
    expect(out).toContain('内容')
  })

  it('保留图片：img 与 src 原样（图片不属于内联颜色）', () => {
    const out = sanitizeArticleHtml(
      '<figure><img src="https://example.com/a.png" alt="图"></figure>',
    )
    const img = parseDom(out).querySelector('img')
    expect(img).not.toBeNull()
    expect(img?.getAttribute('src')).toBe('https://example.com/a.png')
  })

  it('保留 class 语义色：shiki 高亮 class 存活（颜色随主题切换）', () => {
    const out = sanitizeArticleHtml(
      '<pre><code class="lumi-shiki-code"><span class="lumi-sh-5c6370">const</span></code></pre>',
    )
    const token = parseDom(out).querySelector('span.lumi-sh-5c6370')
    expect(token).not.toBeNull()
    expect(token?.className).toContain('lumi-sh-5c6370')
  })

  it('完整管线（transform 开）同样中和内联颜色（边界是最终一道）', async () => {
    const out = await renderArticleHtml(
      '<p><font color="#333">a</font><span style="color:red">b</span></p>',
      { conversion: 'off', bionic: true, codeTheme: null },
    )
    expect(out).not.toMatch(/\bstyle\s*=/i)
    expect(out).not.toMatch(/\bcolor\s*=/i)
    expect(out).toContain('a')
    expect(out).toContain('b')
  })
})
