/** translation-blocks — 分块与 overlay 单元测试（jsdom DOM API）。 */

import { describe, expect, it, beforeEach } from 'vitest'
import {
  annotateBlocks,
  applyOverlay,
  resetOverlay,
  type ArticleBlock,
} from '../lib/translation-blocks'

function host(html: string): HTMLElement {
  const root = document.createElement('div')
  root.innerHTML = html
  document.body.appendChild(root)
  return root
}

function textsOf(blocks: ArticleBlock[]): string[] {
  return blocks.map((b) => `${b.index}:${b.text}`)
}

beforeEach(() => {
  document.body.innerHTML = ''
})

describe('annotateBlocks', () => {
  it('按文档顺序编号块级元素；pre/code 跳过；空块跳过', () => {
    const root = host(`
      <h1>标题</h1>
      <p>第一段。</p>
      <pre><code>const x = 1;</code></pre>
      <p>  </p>
      <p>第二段。</p>
      <figure><img src="x.png" alt=""><figcaption>图注文字</figcaption></figure>
    `)
    const blocks = annotateBlocks(root)
    expect(textsOf(blocks)).toEqual([
      '0:标题',
      '1:第一段。',
      '2:第二段。',
      '3:图注文字',
    ])
    // 编号写入 DOM（overlay 配对依据）
    expect(root.querySelector('p[data-lb-index="1"]')).not.toBeNull()
    // pre 内元素没有编号
    expect(root.querySelector('pre [data-lb-index]')).toBeNull()
  })

  it('嵌套块由最外层代表整块，不拆碎片；重复调用幂等', () => {
    const root = host(`
      <blockquote><p>引用里的段落。</p></blockquote>
      <ul><li>列表项一</li><li>列表项二</li></ul>
    `)
    const blocks = annotateBlocks(root)
    expect(textsOf(blocks)).toEqual([
      '0:引用里的段落。',
      '1:列表项一',
      '2:列表项二',
    ])
    const again = annotateBlocks(root)
    expect(again.map((b) => b.index)).toEqual([0, 1, 2])
  })
})

describe('applyOverlay', () => {
  it('bilingual：顶层块包成 .lb-pair（原文左译文右）；译文是纯文本', () => {
    const root = host('<p>原文一段。</p>')
    annotateBlocks(root)
    applyOverlay(root, {
      texts: new Map([[0, '译文一段。']]),
      mode: 'bilingual',
    })
    const pair = root.querySelector('.lb-pair')
    expect(pair).not.toBeNull()
    expect(pair?.textContent).toContain('原文一段。')
    expect(pair?.textContent).toContain('译文一段。')
    const translationNode = root.querySelector('[data-lb-t="1"]')
    expect(translationNode?.children).toHaveLength(0) // 无 HTML 子节点
  })

  it('translated：原文块隐藏、译文在原位；无译文的块与 pre 保留', () => {
    const root = host('<p>要隐藏的原文。</p><p>没有译文的一段。</p><pre>code</pre>')
    annotateBlocks(root)
    applyOverlay(root, {
      texts: new Map([[0, '译文。']]),
      mode: 'translated',
    })
    const hidden = root.querySelectorAll('p')[0] as HTMLElement
    expect(hidden.style.display).toBe('none')
    expect(root.querySelector('.lb-translation')?.textContent).toBe('译文。')
    // 无译文块保留可见
    const kept = root.querySelectorAll('p')[1] as HTMLElement
    expect(kept.style.display).toBe('')
    expect(root.querySelector('pre')?.textContent).toBe('code')
  })

  it('resetOverlay 完整还原 DOM（拆对、删译文、恢复隐藏）', () => {
    const root = host('<p>原文。</p>')
    annotateBlocks(root)
    applyOverlay(root, { texts: new Map([[0, '译文。']]), mode: 'translated' })
    resetOverlay(root)
    expect(root.querySelector('.lb-pair')).toBeNull()
    expect(root.querySelector('[data-lb-t="1"]')).toBeNull()
    const p = root.querySelector('p') as HTMLElement
    expect(p.style.display).toBe('')
    expect(p.textContent).toBe('原文。')
  })
})
