/**
 * FIX-306 — 翻译分段绝不拆开 HTML 实体或代理对（BASELINE_OK 守卫）。
 *
 * 既有边界（逐层验证，无产品改动）：
 * 1. 分段的唯一单位是「块级元素整节点」（annotateBlocks 按文档顺序给
 *    p / h1-h6 / li / blockquote 等编号）——文本永远整块进入管线，
 *    不存在按字符下标切分；
 * 2. 派发分批（chunkTranslationBlocks）只按块装箱：一个块的文本完整
 *    出现在恰好一个批次里，批次边界绝不落在字符中间；
 * 3. 归一化（normalizedBlockText 只折叠空白）与 textContent 注入
 *    （applyOverlay）都是整串操作——星面字符（代理对）与实体解码后的
 *    字符在往返前后逐字符完整。
 *
 * JS 侧按 UTF-16 下标 slice 才会劈开代理对——本套件钉死「没有任何
 * 翻译路径这样做」这一事实；未来引入字符级切分时这里必红。
 */

import { describe, expect, it } from 'vitest'

import {
  annotateBlocks,
  normalizedBlockText,
} from '../lib/translation-blocks'
import {
  QUEUE_MAX_CHARS,
  chunkTranslationBlocks,
} from '../lib/translation-scope'

/** 含星面字符（😀=U+1F600 代理对）、组合附标与实体形态文字的样本。 */
const EMOJI = '😀'
const SAMPLE = `开头${EMOJI}代理对 &amp;nbsp; 实体形态 text &lt;tag&gt; 尾部${EMOJI}`

function mountParagraphs(texts: string[]): HTMLElement {
  const root = document.createElement('div')
  for (const text of texts) {
    const p = document.createElement('p')
    p.textContent = text
    root.appendChild(p)
  }
  document.body.appendChild(root)
  return root
}

describe('FIX-306: 翻译分段以节点为界，字符往返完整', () => {
  it('annotateBlocks：块文本含代理对与实体形态字符且逐字符完整', () => {
    const root = mountParagraphs([SAMPLE, `第二段${EMOJI}`])
    const blocks = annotateBlocks(root)
    expect(blocks).toHaveLength(2)
    expect(blocks[0]!.text).toBe(normalizedBlockText(SAMPLE))
    expect(blocks[0]!.text).toContain(EMOJI)
    expect(blocks[0]!.text).toContain('&amp;')
    expect(blocks[1]!.text.endsWith(EMOJI)).toBe(true)
    // 代理对按码点往返：拆开会产生孤立代理项（0xD800–0xDFFF）。
    for (const block of blocks) {
      for (const ch of block.text) {
        const code = ch.codePointAt(0)!
        expect(code >= 0xd800 && code <= 0xdfff).toBe(false)
      }
    }
    root.remove()
  })

  it('chunkTranslationBlocks：块只在块边界装箱，文本永不跨批拆分', () => {
    const blocks = Array.from({ length: 30 }, (_, i) => ({
      index: i,
      text: `块${i}${EMOJI}${'x'.repeat(400)}`,
    }))
    const chunks = chunkTranslationBlocks(blocks, 8, QUEUE_MAX_CHARS)
    const seen = new Map<number, string>()
    for (const chunk of chunks) {
      for (const block of chunk) {
        expect(seen.has(block.index)).toBe(false)
        seen.set(block.index, block.text)
      }
    }
    // 每块恰好一次且整块出现（逐字符一致——含代理对）。
    expect(seen.size).toBe(blocks.length)
    for (const block of blocks) {
      expect(seen.get(block.index)).toBe(block.text)
    }
  })

  it('超长块也不被切块：单块超过每批字符预算时仍整块成批', () => {
    const huge = `${EMOJI}${'长'.repeat(QUEUE_MAX_CHARS + 100)}${EMOJI}`
    const chunks = chunkTranslationBlocks([{ index: 0, text: huge }])
    expect(chunks).toHaveLength(1)
    expect(chunks[0]![0]!.text).toBe(huge)
    expect(chunks[0]![0]!.text.startsWith(EMOJI)).toBe(true)
    expect(chunks[0]![0]!.text.endsWith(EMOJI)).toBe(true)
  })
})
