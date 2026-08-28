import { describe, expect, it } from 'vitest'
import { sanitizeArticleHtml } from '../lib/sanitize-article-html'

/** 0006 最重要的安全测试：断言 sanitize 输出的 DOM 结构
 * （不测“脚本有没有执行”）。fixture 中的攻击载荷是测试数据，
 * 不是真实 XSS 泄漏。 */

const MALICIOUS_INPUT = [
  '<p>Hello <strong>LumiRSS</strong></p>',
  '<script>alert(1)</script>',
  '<img src="x" onerror="alert(2)">',
  '<a href="javascript:alert(3)">bad</a>',
  '<form action="javascript:alert(4)"><input type="text"><button>go</button></form>',
  '<iframe src="https://evil.example"></iframe>',
  '<style>body { display: none }</style>',
  '<div style="position: fixed">styled</div>',
].join('')

function parseDom(html: string): HTMLElement {
  const container = document.createElement('div')
  container.innerHTML = html
  return container
}

describe('Sanitizer — 安全结构断言', () => {
  it('正常正文元素与内容保留（p / strong）', () => {
    const dom = parseDom(sanitizeArticleHtml('<p>Hello <strong>LumiRSS</strong></p>'))
    expect(dom.querySelector('p')?.textContent).toBe('Hello LumiRSS')
    expect(dom.querySelector('strong')?.textContent).toBe('LumiRSS')
  })

  it('script 被移除（内容也不保留）', () => {
    const dom = parseDom(sanitizeArticleHtml(MALICIOUS_INPUT))
    expect(dom.querySelector('script')).toBeNull()
    expect(dom.textContent).not.toContain('alert(1)')
  })

  it('事件属性 onerror 被移除（img 本身保留）', () => {
    const dom = parseDom(sanitizeArticleHtml(MALICIOUS_INPUT))
    const img = dom.querySelector('img')
    expect(img).not.toBeNull()
    expect(img?.getAttribute('onerror')).toBeNull()
    expect(img?.getAttribute('src')).toBe('x')
  })

  it('javascript: href 被移除（a 不带危险协议）', () => {
    const dom = parseDom(sanitizeArticleHtml(MALICIOUS_INPUT))
    const links = [...dom.querySelectorAll('a')]
    expect(links.length).toBeGreaterThan(0)
    for (const link of links) {
      // DOMPurify 直接移除危险 href（属性不存在），保留安全的
      expect(link.getAttribute('href') ?? '').not.toContain('javascript:')
    }
    expect(dom.querySelector('a[href="javascript:alert(3)"]')).toBeNull()
  })

  it.each(['form', 'input', 'button', 'iframe', 'style'])('%s 被移除（FORBID_TAGS）', (tag) => {
    const dom = parseDom(sanitizeArticleHtml(MALICIOUS_INPUT))
    expect(dom.querySelector(tag)).toBeNull()
  })

  it('inline style 属性被移除（FORBID_ATTR）', () => {
    const dom = parseDom(sanitizeArticleHtml(MALICIOUS_INPUT))
    for (const el of [...dom.querySelectorAll('*')]) {
      expect(el.getAttribute('style')).toBeNull()
    }
    // style 元素的内容也不能以文本形式泄漏
    expect(dom.textContent).not.toContain('display: none')
  })

  it('SVG / MathML 命名空间不允许（USE_PROFILES: html only）', () => {
    const dom = parseDom(
      sanitizeArticleHtml('<svg><circle r="1"></circle></svg><math><mi>x</mi></math>'),
    )
    expect(dom.querySelector('svg, circle')).toBeNull()
    expect(dom.querySelector('math, mi')).toBeNull()
  })
})
