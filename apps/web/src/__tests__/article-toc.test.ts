/** 文章目录提取回归（pool #03）：重复标题、空标题、标题跳级、CJK
 * slug、锚点稳定性与「只补 id 不改语义」。 */

import { describe, expect, it } from 'vitest'
import { headingSlug, withHeadingIds } from '../lib/article-toc'

describe('withHeadingIds', () => {
  it('提取 h2–h4，注入确定性 id', () => {
    const { html, toc } = withHeadingIds(
      '<h2>安装</h2><p>正文</p><h3>依赖</h3><h4>可选依赖</h4>',
    )
    expect(toc).toEqual([
      { id: 'toc-安装', text: '安装', level: 2 },
      { id: 'toc-依赖', text: '依赖', level: 3 },
      { id: 'toc-可选依赖', text: '可选依赖', level: 4 },
    ])
    expect(html).toContain('id="toc-安装"')
    expect(html).toContain('<p>正文</p>')
  })

  it('重复标题追加序号，锚点互不相同且稳定', () => {
    const input = '<h2>用法</h2><p>一</p><h2>用法</h2><p>二</p><h2>用法</h2>'
    const first = withHeadingIds(input)
    expect(first.toc.map((t) => t.id)).toEqual([
      'toc-用法',
      'toc-用法-2',
      'toc-用法-3',
    ])
    // 同一输入再次提取 → 相同 id（锚点稳定）。
    const second = withHeadingIds(input)
    expect(second.toc.map((t) => t.id)).toEqual(first.toc.map((t) => t.id))
  })

  it('空标题跳过；无标题文章返回空目录且 HTML 原样返回', () => {
    const withEmpty = withHeadingIds('<h2>   </h2><h2>有标题</h2>')
    expect(withEmpty.toc).toEqual([
      { id: 'toc-有标题', text: '有标题', level: 2 },
    ])
    const none = withHeadingIds('<p>纯正文，没有标题。</p>')
    expect(none.toc).toEqual([])
    expect(none.html).toBe('<p>纯正文，没有标题。</p>')
  })

  it('标题跳级（h2 直接到 h4）不丢条目、不崩溃', () => {
    const { toc } = withHeadingIds('<h2>一</h2><h4>深层</h4>')
    expect(toc).toEqual([
      { id: 'toc-一', text: '一', level: 2 },
      { id: 'toc-深层', text: '深层', level: 4 },
    ])
  })

  it('标题内的行内标记（strong/em）只取文本，不改变原意', () => {
    const { toc, html } = withHeadingIds('<h2>为什么<strong>重要</strong></h2>')
    expect(toc[0].text).toBe('为什么重要')
    expect(html).toContain('<strong>重要</strong>')
  })

  it('h1/h5/h6 不进目录', () => {
    const { toc } = withHeadingIds('<h1>文章题</h1><h2>节</h2><h5>小点</h5>')
    expect(toc).toEqual([{ id: 'toc-节', text: '节', level: 2 }])
  })
})

describe('headingSlug', () => {
  it('CJK、英文与混合输入', () => {
    expect(headingSlug('安装指南')).toBe('安装指南')
    expect(headingSlug('Quick Start')).toBe('quick-start')
    expect(headingSlug('v2.0 发布!')).toBe('v2-0-发布')
  })

  it('全标点标题回退为 untitled，保证 id 非空', () => {
    expect(headingSlug('!!!')).toBe('untitled')
  })
})
