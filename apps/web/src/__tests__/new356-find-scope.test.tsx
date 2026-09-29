/** NEW-356 文章内查找导航（范围扩展）— reader-find 层过滤器 + 查找条
 * 范围选择（jsdom）。
 *
 * 覆盖：findMatches 的原文/译文/双层范围（译文层 = .lb-translation
 * overlay 节点；缺省 'all' 向后兼容既有行为）；hasTranslationLayer；
 * 查找条（译文层存在 → 范围选择出现，切换重查并如实计数；译文层
 * 消失 → 范围回退双层且选择器隐藏）。 */

import { act, fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import ArticleFindBar from '../components/ArticleFindBar'
import { findMatches, hasTranslationLayer } from '../lib/reader-find'

function buildArticle(withTranslation: boolean): HTMLElement {
  const root = document.createElement('div')
  root.className = 'lumi-reader-article'
  const pairHtml = withTranslation
    ? `<div class="lb-pair" data-lb-pair="1">
         <p data-lb-index="0">The original paragraph about reading</p>
         <div class="lb-translation" data-lb-t="1" data-lb-mode="bilingual">关于阅读的原始段落译文</div>
       </div>`
    : `<p data-lb-index="0">The original paragraph about reading</p>`
  root.innerHTML = `
    ${pairHtml}
    <p data-lb-index="1">Another paragraph mentioning reading twice — reading is a craft</p>`
  document.body.appendChild(root)
  return root
}

describe('NEW-356 查找范围（reader-find）', () => {
  it('译文层检测：有 .lb-translation → true；无 → false；null → false', () => {
    expect(hasTranslationLayer(buildArticle(true))).toBe(true)
    expect(hasTranslationLayer(buildArticle(false))).toBe(false)
    expect(hasTranslationLayer(null)).toBe(false)
  })

  it('范围过滤：original 跳过译文节点；translated 只查译文；all 两层都查（默认）', () => {
    const root = buildArticle(true)
    const all = findMatches(root, '阅读')
    expect(all.length).toBe(1)
    expect(findMatches(root, 'reading').length).toBe(3) // 原文两处 + 译文里无
    // 'reading' 出现在两个原文 p + 0 译文；上面 3 = p0(1) + p1(2)
    expect(findMatches(root, 'reading', 'original').length).toBe(3)
    expect(findMatches(root, 'reading', 'translated').length).toBe(0)
    // 译文专属词
    expect(findMatches(root, '关于阅读', 'all').length).toBe(1)
    expect(findMatches(root, '关于阅读', 'original').length).toBe(0)
    expect(findMatches(root, '关于阅读', 'translated').length).toBe(1)
    // 缺省参数 = 'all'（既有调用点零改动兼容）
    expect(findMatches(root, '关于阅读')).toHaveLength(1)
  })

  it('空查询 / 空白查询 → 空（诚实不匹配）', () => {
    const root = buildArticle(true)
    expect(findMatches(root, '', 'original')).toEqual([])
    expect(findMatches(root, '   ', 'translated')).toEqual([])
  })
})

describe('NEW-356 查找条范围选择', () => {
  it('译文层存在：范围选择出现；切换范围重新计数（译文层 0 命中如实显示）', () => {
    const root = buildArticle(true)
    render(<ArticleFindBar open onClose={() => {}} getRoot={() => root} />)
    const group = screen.getByRole('radiogroup', { name: '查找范围' })
    expect(group).toBeTruthy()
    const input = screen.getByLabelText('查找正文') as HTMLInputElement
    // 原文层词：双层 3 处（当前第 1 处）
    fireEvent.change(input, { target: { value: 'reading' } })
    expect(screen.getByText(/1\/3 处命中/)).toBeTruthy()
    // 切到译文 → 0 命中（诚实「无结果」）
    fireEvent.click(screen.getByRole('radio', { name: '译文' }))
    expect(screen.getByText('无结果')).toBeTruthy()
    // 切到原文 → 3 处（重新从第 1 处开始）
    fireEvent.click(screen.getByRole('radio', { name: '原文' }))
    expect(screen.getByText(/1\/3 处命中/)).toBeTruthy()
  })

  it('纯原文态：范围选择不出现（既有行为零打扰）', () => {
    const root = buildArticle(false)
    render(<ArticleFindBar open onClose={() => {}} getRoot={() => root} />)
    expect(screen.queryByRole('radiogroup', { name: '查找范围' })).toBeNull()
    const input = screen.getByLabelText('查找正文') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'reading' } })
    expect(screen.getByText(/1\/3 处命中/)).toBeTruthy()
  })

  it('范围停在译文但译文层消失 → 自动回退双层', async () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    host.appendChild(buildArticle(true))
    render(<ArticleFindBar open onClose={() => {}} getRoot={() => host.querySelector('.lumi-reader-article')} />)
    expect(screen.getByRole('radiogroup', { name: '查找范围' })).toBeTruthy()
    fireEvent.click(screen.getByRole('radio', { name: '译文' }))
    // 译文层被移除（切回原文视图）
    act(() => {
      host.querySelector('.lb-translation')?.remove()
    })
    // 重渲染触发（state 变化：改查询触发 effect + memo 重算）
    const input = screen.getByLabelText('查找正文') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'craft' } })
    // 范围选择消失（无译文层），范围已回退 'all'
    expect(screen.queryByRole('radiogroup', { name: '查找范围' })).toBeNull()
    expect(screen.getByText(/1\/1 处命中/)).toBeTruthy()
  })
})
