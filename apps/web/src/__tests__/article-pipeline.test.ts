/** article-pipeline 测试 — 0012 Gate 4/9（安全模型 AC16/AC17）。
 *
 * 核心断言：transforms 之后的输出仍处于 DOMPurify 安全边界内——
 * 恶意 HTML（script/onerror/javascript:/iframe/style/form/svg
 * namespace/malformed）经管线后危险内容全部消失。 */

import { describe, expect, it } from 'vitest'
import { renderArticleHtml, clearConverterCache } from '../lib/article-pipeline'

const OFF = { conversion: 'off', bionic: false, codeTheme: null } as const

describe('renderArticleHtml — 关闭所有 transform（0006 兼容路径）', () => {
  it('与直接 sanitize 等价', async () => {
    const raw = '<p>hello <strong>world</strong></p><script>alert(1)</script>'
    const out = await renderArticleHtml(raw, OFF)
    expect(out).not.toContain('<script')
    expect(out).toContain('<strong>world</strong>')
  })
})

describe('renderArticleHtml — 恶意 HTML regression（AC17）', () => {
  const malicious = [
    '<p onclick="alert(1)">click</p>',
    '<img src=x onerror="alert(1)">',
    '<a href="javascript:alert(1)">bad</a>',
    '<iframe src="https://evil.example"></iframe>',
    '<style>body{background:red}</style><p>x</p>',
    '<form action="https://evil.example"><input type="text"></form>',
    '<svg><script>alert(1)</script></svg>',
    '<math><mtext></mtext></math><p>x</p>',
    '<p>broken <div <span>malformed',
    '<p data-x="1" style="color:red">styled</p>',
  ]

  for (const raw of malicious) {
    it(`transforms 后仍清洗：${raw.slice(0, 40)}`, async () => {
      for (const opts of [
        OFF,
        { conversion: 's2t' as const, bionic: false, codeTheme: null },
        { conversion: 'off' as const, bionic: true, codeTheme: null },
        { conversion: 't2s' as const, bionic: true, codeTheme: null },
      ]) {
        const out = await renderArticleHtml(raw, opts)
        expect(out).not.toMatch(/on[a-z]+\s*=/i)
        expect(out).not.toContain('<script')
        expect(out).not.toContain('<iframe')
        expect(out).not.toContain('<style')
        expect(out).not.toContain('<form')
        expect(out).not.toContain('javascript:')
        expect(out).not.toMatch(/<svg|<math/i)
        expect(out).not.toMatch(/\bstyle\s*=/i)
      }
    })
  }
})

describe('renderArticleHtml — OpenCC 简繁转换（真实词典）', () => {
  it('s2t：简体 → 繁体', async () => {
    clearConverterCache()
    const out = await renderArticleHtml('<p>学习汉字，阅读软件。</p>', {
      conversion: 's2t',
      bionic: false,
      codeTheme: null,
    })
    // s2t 是字符级转换（软件→軟件；「軟體」是台措辞，归 tw 档）
    expect(out).toContain('學習漢字')
    expect(out).toContain('閱讀軟件')
  })

  it('t2s：繁体 → 简体', async () => {
    clearConverterCache()
    const out = await renderArticleHtml('<p>學習漢字，閱讀軟體。</p>', {
      conversion: 't2s',
      bionic: false,
      codeTheme: null,
    })
    // t2s 字符级：軟體→软体（「软件」是简体习惯词，反向归 tw→cn 档）
    expect(out).toContain('学习汉字')
    expect(out).toContain('阅读软体')
  })

  it('tw：简体 → 台湾正体（含用词转换）', async () => {
    clearConverterCache()
    const out = await renderArticleHtml('<p>软件与网络。</p>', {
      conversion: 'tw',
      bionic: false,
      codeTheme: null,
    })
    expect(out).toContain('軟體')
    expect(out).toContain('網路')
  })

  it('HTML 标签 / 属性 / URL 不被转换', async () => {
    clearConverterCache()
    const raw = '<p class="学习">学习</p><a href="https://zh.wikipedia.org/wiki/学习">链接</a>'
    const out = await renderArticleHtml(raw, { conversion: 's2t', bionic: false, codeTheme: null })
    // 文本内容转换
    expect(out).toContain('學習')
    // 属性与 URL 保持原样（text node walker 天然不触及；
    // DOMParser serialize 不做百分号编码，保持字面）
    expect(out).toContain('class="学习"')
    expect(out).toContain('wiki/学习')
  })

  it('code/pre 内容默认不转换', async () => {
    clearConverterCache()
    const raw = '<p>学习</p><pre><code>let 学习 = 1</code></pre><p><code>var 学习</code></p>'
    const out = await renderArticleHtml(raw, { conversion: 's2t', bionic: false, codeTheme: null })
    expect(out).toContain('學習</p>') // 段落转换
    expect(out).toContain('let 学习 = 1') // pre 不转换
    expect(out).toContain('var 学习') // 行内 code 不转换
  })

  it('切回原文完全恢复（off = 纯 sanitize）', async () => {
    clearConverterCache()
    const raw = '<p>学习汉字</p>'
    const converted = await renderArticleHtml(raw, { conversion: 's2t', bionic: false, codeTheme: null })
    expect(converted).toContain('學習漢字')
    const restored = await renderArticleHtml(raw, OFF)
    expect(restored).toContain('学习汉字')
    expect(restored).not.toContain('學習')
  })
})

describe('renderArticleHtml — Bionic 词首强调（Gate 9）', () => {
  it('拉丁词首被 <b class="lumi-bionic"> 包裹', async () => {
    const out = await renderArticleHtml('<p>The quick brown fox</p>', {
      conversion: 'off',
      bionic: true,
      codeTheme: null,
    })
    expect(out).toContain('<b class="lumi-bionic">Th</b>e')
    expect(out).toContain('<b class="lumi-bionic">qu</b>ick')
    expect(out).toContain('<b class="lumi-bionic">br</b>own')
  })

  it('CJK 字符不套 <b>（AC：不给中文字符套标签）', async () => {
    const out = await renderArticleHtml('<p>中文内容不应被强调</p>', {
      conversion: 'off',
      bionic: true,
      codeTheme: null,
    })
    expect(out).toContain('中文内容不应被强调')
    expect(out).not.toContain('lumi-bionic')
  })

  it('code/pre/kbd/a/heading 默认跳过', async () => {
    const out = await renderArticleHtml(
      '<h2>Reading</h2><p><code>const x</code></p><pre>hello world</pre><a href="#">link text</a><p>normal words</p>',
      { conversion: 'off', bionic: true, codeTheme: null },
    )
    expect(out).toContain('<code>const x</code>')
    expect(out).toContain('<pre>hello world</pre>')
    expect(out).toContain('<a href="#">link text</a>')
    // 段落内正常处理
    expect(out).toContain('lumi-bionic')
  })

  it('不产生嵌套 strong（只包 plain text node）', async () => {
    const out = await renderArticleHtml('<p><strong>bold words</strong></p>', {
      conversion: 'off',
      bionic: true,
      codeTheme: null,
    })
    // strong 内的词首同样强调是预期行为，但不得出现 b>strong 嵌套
    expect(out).not.toMatch(/<b[^>]*><strong/)
    expect(out).not.toMatch(/<strong[^>]*><b[^>]*><b/)
  })

  it('混合开关：conversion + bionic 同时启用', async () => {
    clearConverterCache()
    const out = await renderArticleHtml('<p>学习 English words。</p>', {
      conversion: 's2t',
      bionic: true,
      codeTheme: null,
    })
    expect(out).toContain('學習')
    expect(out).toContain('lumi-bionic')
  })
})

describe('renderArticleHtml — Shiki 代码高亮（Gate 8）', () => {
  it('含 code 文章 + 主题开启 → 产生 lumi-shiki span（真实 shiki lazy 加载）', async () => {
    const raw =
      '<pre><code class="language-typescript">const x: number = 42</code></pre>'
    const out = await renderArticleHtml(raw, {
      conversion: 'off',
      bionic: false,
      codeTheme: 'github-light',
    })
    expect(out).toContain('lumi-shiki-code')
    expect(out).toContain('lumi-sh-')
    // token 内容经 DOMPurify 后保留
    expect(out).toContain('const')
    expect(out).toContain('42')
  })

  it('codeTheme = null（设置关闭）→ 不高亮，原样保留', async () => {
    const raw = '<pre><code class="language-python">print(1)</code></pre>'
    const out = await renderArticleHtml(raw, {
      conversion: 'off',
      bionic: false,
      codeTheme: null,
    })
    expect(out).not.toContain('lumi-shiki-code')
    expect(out).toContain('print(1)')
  })

  it('未识别语言 → plaintext 原样保留', async () => {
    const raw = '<pre><code class="language-brainfuck">+++</code></pre>'
    const out = await renderArticleHtml(raw, {
      conversion: 'off',
      bionic: false,
      codeTheme: 'github-light',
    })
    expect(out).toContain('+++')
    expect(out).not.toContain('lumi-shiki-code')
  })

  it('无 code 文章 + 主题开启 → 纯 sanitize 路径（不加载 shiki）', async () => {
    const raw = '<p>纯文本文章，没有代码。</p>'
    const out = await renderArticleHtml(raw, {
      conversion: 'off',
      bionic: false,
      codeTheme: 'github-light',
    })
    expect(out).toContain('纯文本文章')
  })

  it('高亮输出不含 inline style（与 sanitize FORBID_ATTR style 协同）', async () => {
    const raw = '<pre><code class="language-json">{"a": 1}</code></pre>'
    const out = await renderArticleHtml(raw, {
      conversion: 'off',
      bionic: false,
      codeTheme: 'github-dark',
    })
    expect(out).not.toMatch(/\bstyle\s*=/i)
  })

  it('恶意 code 内容高亮后仍被清洗', async () => {
    const raw =
      '<pre><code class="language-javascript">alert(1)</code></pre><script>evil()</script>'
    const out = await renderArticleHtml(raw, {
      conversion: 'off',
      bionic: false,
      codeTheme: 'github-light',
    })
    expect(out).not.toContain('<script')
    // alert(1) 是代码文本，合法保留（textContent 注入，不执行）
    expect(out).toContain('alert')
  })
})
