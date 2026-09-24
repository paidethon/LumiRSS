/** N087 按章节/范围翻译 —— 范围选择与有界分批的纯逻辑：
 * 章节区间推导（与 article-chapters 同规则）、块子集选取、预计字符量、
 * 批次切分。 */

import { describe, expect, it } from 'vitest'
import {
  chunkTranslationBlocks,
  collectChapterRanges,
  estimateChars,
  selectScopeBlocks,
  type ChapterRange,
} from '../lib/translation-scope'
import type { ArticleBlock } from '../lib/translation-blocks'

function mountArticle(html: string): HTMLElement {
  const root = document.createElement('div')
  root.innerHTML = `<div class="article-content">${html}</div>`
  document.body.appendChild(root)
  return root
}

function annotate(root: HTMLElement): void {
  const selector = 'p, h1, h2, h3, h4, h5, h6, li, blockquote, figcaption, dd, dt'
  let index = 0
  for (const el of Array.from(root.querySelectorAll(selector))) {
    if ((el.textContent ?? '').trim() === '') continue
    el.setAttribute('data-lb-index', String(index))
    index += 1
  }
}

function blocks(list: Array<[number, string]>): ArticleBlock[] {
  return list.map(([index, text]) => ({ index, text }))
}

describe('N087 collectChapterRanges', () => {
  it('按 h2/h3/h4 划分章节；标题本身计入章节块；首章之前的块并入第一章节', () => {
    const root = mountArticle(`
      <p>导语（首章之前）</p>
      <h2>第一章</h2>
      <p>甲</p>
      <h3>小节</h3>
      <p>乙</p>
      <h2>第二章</h2>
      <p>丙</p>
    `)
    annotate(root)
    const ranges = collectChapterRanges(root)
    expect(ranges).toHaveLength(2)
    // 导语并入第一章节（containingChapterId 同规则）；h3 小节留在章一
    expect(ranges[0].blockIndexes).toEqual([0, 1, 2, 3, 4])
    expect(ranges[1].blockIndexes).toEqual([5, 6])
    expect(ranges[0].headingIndex).toBe(1)
    expect(ranges[1].headingIndex).toBe(5)
  })

  it('同级标题开新章节；更低级标题留在当前章节；嵌套块归属章节', () => {
    const root = mountArticle(`
      <h2>章一</h2>
      <p>a</p>
      <h4>章一的小标题（留在这章）</h4>
      <p>b</p>
      <h2>章二</h2>
      <figure><figcaption>c</figcaption></figure>
    `)
    annotate(root)
    const ranges = collectChapterRanges(root)
    expect(ranges).toHaveLength(2)
    expect(ranges[0].blockIndexes).toEqual([0, 1, 2, 3])
    expect(ranges[1].blockIndexes).toEqual([4, 5])
  })

  it('无标题 → 单一全文区间；空内容 → 空区间', () => {
    const plain = mountArticle('<p>一</p><p>二</p>')
    annotate(plain)
    expect(collectChapterRanges(plain)).toEqual([
      { headingIndex: null, blockIndexes: [0, 1] },
    ])
    const empty = mountArticle('<p>没有编号</p>')
    expect(collectChapterRanges(empty)).toEqual([])
  })
})

describe('N087 selectScopeBlocks', () => {
  const list = blocks([
    [0, 'zero'],
    [1, 'one'],
    [2, 'two'],
    [3, 'three'],
  ])
  const ranges: ChapterRange[] = [
    { headingIndex: 0, blockIndexes: [0, 1] },
    { headingIndex: 2, blockIndexes: [2, 3] },
  ]

  it('全文 = 全部块', () => {
    const result = selectScopeBlocks(list, 'all')
    expect(result.blocks.map((b) => b.index)).toEqual([0, 1, 2, 3])
  })

  it('当前章节 = 当前块所在章节的全部块（含标题），绝无越界块', () => {
    const result = selectScopeBlocks(list, 'chapter', {
      ranges,
      currentBlockIndex: 3,
    })
    expect(result.blocks.map((b) => b.index)).toEqual([2, 3])
  })

  it('当前块不在任何章节 → 回退第一章节', () => {
    const result = selectScopeBlocks(list, 'chapter', {
      ranges,
      currentBlockIndex: null,
    })
    expect(result.blocks.map((b) => b.index)).toEqual([0, 1])
  })

  it('从当前块到结尾 = index ≥ 当前块；无可见块 → 全文回退', () => {
    const tail = selectScopeBlocks(list, 'toEnd', { currentBlockIndex: 2 })
    expect(tail.blocks.map((b) => b.index)).toEqual([2, 3])
    const all = selectScopeBlocks(list, 'toEnd', { currentBlockIndex: null })
    expect(all.blocks.map((b) => b.index)).toEqual([0, 1, 2, 3])
  })
})

describe('N087 estimateChars + chunkTranslationBlocks', () => {
  it('预计字符量 = 归一化源文本长度之和', () => {
    expect(estimateChars(blocks([[0, 'abc'], [1, '  de  f ']]))).toBe(7)
  })

  it('批次切分：块数与字符上限都生效，保序不丢块', () => {
    const many = blocks(
      Array.from({ length: 19 }, (_, i) => [i, `block-${i}`]) as Array<[number, string]>,
    )
    const chunks = chunkTranslationBlocks(many, 8, 6000)
    expect(chunks.map((chunk) => chunk.length)).toEqual([8, 8, 3])
    expect(chunks.flat().map((b) => b.index)).toEqual(many.map((b) => b.index))

    const heavy = blocks(
      Array.from({ length: 4 }, (_, i) => [i, 'x'.repeat(4000)]) as Array<[number, string]>,
    )
    const heavyChunks = chunkTranslationBlocks(heavy, 8, 6000)
    expect(heavyChunks.map((chunk) => chunk.length)).toEqual([1, 1, 1, 1])
  })
})
