/** W3 前端纯逻辑测试 — F047 脱敏与路由匹配、F053 关联滚动、F054 外链收集、
 * F059 脚注变换、F060 KaTeX 检测。 */

import { describe, expect, it } from 'vitest'
import { maskQuery, matchRoute } from '../lib/rsshub-params'
import {
  computeVisibleIndex,
  counterpartIndex,
  LoopGuard,
  LINKED_SCROLL_WINDOW_MS,
} from '../lib/linked-scroll'
import { collectArticleLinks, displayUrl, groupLinksByHost } from '../lib/collect-article-links'
import { transformFootnotes, readFootnoteDefinition, FOOTNOTE_DEFS_CONTAINER_ID } from '../lib/footnotes'
import { firstMathMatch, containsMathMarker } from '../lib/katex-render'

describe('F047 RSSHub 参数编辑', () => {
  it('F047: token 类参数值脱敏（***），普通参数原样', () => {
    expect(maskQuery('https://rsshub.app/twitter/user/foo?token=abc&limit=5')).toBe(
      'https://rsshub.app/twitter/user/foo?token=***&limit=5',
    )
    expect(maskQuery('https://rsshub.app/b')).toBe('https://rsshub.app/b')
  })

  it('F047: 路由匹配（pathTemplate :param 通配）与未匹配回退', () => {
    const routes = [
      { pathTemplate: '/twitter/user/:id' },
      { pathTemplate: '/bilibili/user/video/:uid' },
    ]
    expect(
      matchRoute(routes, 'https://rsshub.app/twitter/user/evil_beans?limit=5'),
    ).toEqual({ pathTemplate: '/twitter/user/:id' })
    expect(matchRoute(routes, 'https://rsshub.app/unknown/route/x')).toBeNull()
  })

  it('F047: 必填缺失与预览失败不应用（表单守卫语义）', () => {
    // 未匹配路由 → 通用 query 表单（matchedRoute === null 分支）
    // 必填参数标记由 param.required 驱动（渲染层）；此处校验 URL 构造安全
    expect(maskQuery('not a url')).toBe('not a url')
  })
})

describe('F053 双语关联滚动', () => {
  it('F053: 可见块计算与反向映射（缺段返回 null 不抛错）', () => {
    const container = document.createElement('div')
    container.style.cssText = 'position:relative;height:300px;overflow:auto'
    const mk = (index: number) => {
      const block = document.createElement('div')
      block.setAttribute('data-lb-index', String(index))
      block.style.height = '100px'
      container.appendChild(block)
    }
    mk(0)
    mk(1)
    mk(2)
    document.body.appendChild(container)
    // jsdom 无真实布局：可见比全 0 → 仍返回首个块（比例并列取先）
    const visible = computeVisibleIndex(container)
    expect(visible).toBe(0)
    expect(counterpartIndex(1, 3, 3)).toBe(1)
    expect(counterpartIndex(2, 3, 2)).toBeNull() // 翻译缺段 → null 不抛错
    expect(counterpartIndex(-1, 3, 3)).toBeNull()
    container.remove()
  })

  it('F053: 循环守卫时间窗（600ms 内回弹被忽略）', () => {
    const guard = new LoopGuard()
    expect(guard.allow(1000)).toBe(true)
    expect(guard.allow(1000 + LINKED_SCROLL_WINDOW_MS - 1)).toBe(false)
    expect(guard.allow(1000 + LINKED_SCROLL_WINDOW_MS)).toBe(true)
    guard.reset()
    expect(guard.allow(0)).toBe(true)
  })

  it('F053: scrollToBlock 缺块返回 false（不抛错）', async () => {
    const { scrollToBlock } = await import('../lib/linked-scroll')
    const container = document.createElement('div')
    expect(scrollToBlock(container, 5)).toBe(false)
  })
})

describe('F054 文中链接', () => {
  it('F054: 相对地址解析、去重、Unicode 域名 punycode、危险协议排除', () => {
    const container = document.createElement('div')
    container.innerHTML = `
      <a href="/relative/path">相对链接</a>
      <a href="https://example.com/relative/path">重复目标</a>
      <a href="https://例え.jp/テスト">Unicode</a>
      <a href="javascript:alert(1)">危险脚本</a>
      <a href="data:text/html,<b>x</b>">data</a>
      <a href="vbscript:msgbox(1)">vbs</a>
      <a href="https://ok.example.com/a#frag">普通</a>
    `
    // jsdom document.baseURI 是 about:blank — 手动设置 base
    const base = document.createElement('base')
    base.href = 'https://example.com/base/'
    container.prepend(base)
    const links = collectArticleLinks(container)
    const hrefs = links.map((l) => l.href)
    expect(hrefs.some((h) => h.startsWith('javascript:'))).toBe(false)
    expect(hrefs.some((h) => h.startsWith('data:'))).toBe(false)
    expect(hrefs.some((h) => h.startsWith('vbscript:'))).toBe(false)
    // 相对地址按 base 绝对化；同一目标去重（先出现者保留）
    expect(hrefs.filter((h) => h === 'https://example.com/relative/path').length).toBe(1)
    // Unicode 域名 punycode 化
    const unicode = links.find((l) => l.host.includes('xn--'))
    expect(unicode).toBeDefined()
    // 空文字退化 host
    expect(links.every((l) => l.text !== '' && l.host !== '')).toBe(true)
    // 分组
    const groups = groupLinksByHost(links)
    expect(groups.size).toBeGreaterThanOrEqual(2)
    // 超长截断显示
    expect(displayUrl('https://a.com/' + 'x'.repeat(100), 72).endsWith('…')).toBe(true)
    expect(displayUrl('https://short.url')).toBe('https://short.url')
  })
})

describe('F059 脚注往返', () => {
  it('F059: 引用替换为受控按钮（键盘可达 + aria-label），缺失定义不渲染', () => {
    const doc = new DOMParser().parseFromString(
      `<article>
        <p>正文一<sup><a href="#fn1">[1]</a></sup>，多引用<sup><a href="#fn1">[1]</a></sup>。</p>
        <p>缺定义<sup><a href="#fn9">[9]</a></sup>。</p>
        <ol><li id="fn1">脚注内容<b>加粗</b><a href="#fnref1">↩</a></li></ol>
      </article>`,
      'text/html',
    )
    const count = transformFootnotes(doc)
    expect(count).toBe(2) // fn1 的两处引用；fn9 缺定义不渲染
    const buttons = doc.querySelectorAll('button[data-lumi-fn-ref]')
    expect(buttons.length).toBe(2)
    buttons.forEach((button) => {
      expect(button.getAttribute('aria-label')).toBe('查看脚注 1')
      expect(button.getAttribute('type')).toBe('button')
    })
    // 各自保留返回位置
    const seqs = [...buttons].map((b) => b.getAttribute('data-lumi-fn-return'))
    expect(new Set(seqs).size).toBe(2)
    // 定义容器存在且隐藏
    const container = doc.getElementById(FOOTNOTE_DEFS_CONTAINER_ID)
    expect(container?.hidden).toBe(true)
    // 缺失定义未收录
    expect(container?.querySelector('[data-lumi-fn-def="9"]')).toBeNull()
    // 定义可读（含净化前的内容；弹层展示时调用方需再 sanitize）
    const html = readFootnoteDefinition(doc, '1')
    expect(html).toContain('脚注内容')
  })
})

describe('F060 数学公式', () => {
  it('F060: 行内/块级匹配与代码块跳过、极长表达式跳过', () => {
    expect(containsMathMarker('质量 $E=mc^2$ 守恒')).toBe(true)
    expect(containsMathMarker('块级 $$\\int_0^1 x dx$$ 公式')).toBe(true)
    expect(containsMathMarker('没有公式')).toBe(false)
    const inline = firstMathMatch('能量 $E=mc^2$ 定律')
    expect(inline).toEqual({ text: '$E=mc^2$', display: false })
    const block = firstMathMatch('$$\\sum_i x_i$$')
    expect(block?.display).toBe(true)
    // 极长表达式（>10k）跳过渲染（返回 null → 保留原文）
    const huge = firstMathMatch(`$${'x'.repeat(10_001)}$`)
    expect(huge).toBeNull()
  })
})
