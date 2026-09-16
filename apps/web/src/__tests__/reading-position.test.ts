/** 阅读位置存储回归（pool #01）：按 ItemRef 记忆、LRU 有界、损坏数据
 * 安全回退、锚点文本规范化与精确匹配。几何滚动本身在浏览器里，不在
 * jsdom 断言范围内。 */

import { beforeEach, describe, expect, it } from 'vitest'
import {
  captureAnchorText,
  findAnchorElement,
  forgetReadingPositionsForTest,
  loadReadingPosition,
  saveReadingPosition,
} from '../lib/reading-position'

beforeEach(() => {
  forgetReadingPositionsForTest()
})

describe('reading-position 存储', () => {
  it('按 entryRef 保存并恢复 ratio 与锚点', () => {
    saveReadingPosition('rss:e1.a', {
      ratio: 0.42,
      anchorText: '第二段开头',
      savedAt: '2026-09-17T00:00:00Z',
    })
    expect(loadReadingPosition('rss:e1.a')).toEqual({
      ratio: 0.42,
      anchorText: '第二段开头',
      savedAt: '2026-09-17T00:00:00Z',
    })
    expect(loadReadingPosition('rss:e1.b')).toBeNull()
  })

  it('ratio 越界被钳制到 0..1，空锚点归一为 null', () => {
    saveReadingPosition('rss:x', {
      ratio: 1.7,
      anchorText: '   ',
      savedAt: '2026-09-17T00:00:00Z',
    })
    const saved = loadReadingPosition('rss:x')
    expect(saved?.ratio).toBe(1)
    expect(saved?.anchorText).toBeNull()
  })

  it('超出容量（LRU）时淘汰最早访问的条目，不无限增长', () => {
    for (let i = 0; i < 205; i++) {
      saveReadingPosition(`rss:e${i}`, {
        ratio: 0.5,
        anchorText: null,
        savedAt: '2026-09-17T00:00:00Z',
      })
    }
    expect(loadReadingPosition('rss:e0')).toBeNull()
    expect(loadReadingPosition('rss:e4')).toBeNull()
    expect(loadReadingPosition('rss:e5')).not.toBeNull()
    expect(loadReadingPosition('rss:e204')).not.toBeNull()
  })

  it('重复保存同一条目会提升其 LRU 新鲜度', () => {
    for (let i = 0; i < 200; i++) {
      saveReadingPosition(`rss:e${i}`, {
        ratio: 0.5,
        anchorText: null,
        savedAt: '2026-09-17T00:00:00Z',
      })
    }
    // e0 是最老的，重新保存后变成最新。
    saveReadingPosition('rss:e0', {
      ratio: 0.9,
      anchorText: null,
      savedAt: '2026-09-17T00:01:00Z',
    })
    saveReadingPosition('rss:new', {
      ratio: 0.1,
      anchorText: null,
      savedAt: '2026-09-17T00:02:00Z',
    })
    expect(loadReadingPosition('rss:e0')).not.toBeNull()
    expect(loadReadingPosition('rss:e1')).toBeNull()
  })

  it('损坏的 localStorage 数据不会抛错，视为无历史', () => {
    window.localStorage.setItem('lumirss-reading-positions', '{not json')
    expect(loadReadingPosition('rss:e1')).toBeNull()
    window.localStorage.setItem(
      'lumirss-reading-positions',
      JSON.stringify({ v: 99, order: 'oops' }),
    )
    expect(loadReadingPosition('rss:e1')).toBeNull()
    // 且可以正常继续写入。
    saveReadingPosition('rss:e1', {
      ratio: 0.3,
      anchorText: null,
      savedAt: '2026-09-17T00:00:00Z',
    })
    expect(loadReadingPosition('rss:e1')?.ratio).toBe(0.3)
  })
})

describe('锚点匹配', () => {
  it('captureAnchorText 规范化空白并截断', () => {
    const el = document.createElement('p')
    el.textContent = '  第一段　　正文\t继续  '
    expect(captureAnchorText(el)).toBe('第一段 正文 继续')
    expect(captureAnchorText(el)!.length).toBeLessThanOrEqual(64)
    const empty = document.createElement('p')
    expect(captureAnchorText(empty)).toBeNull()
    expect(captureAnchorText(null)).toBeNull()
  })

  it('findAnchorElement 按文本前缀找到同一段落', () => {
    const container = document.createElement('div')
    const article = document.createElement('div')
    article.className = 'lumi-reader-article'
    for (let i = 1; i <= 5; i++) {
      const p = document.createElement('p')
      p.textContent = `第 ${i} 段内容`
      article.appendChild(p)
    }
    container.appendChild(article)

    expect(
      findAnchorElement(container, captureAnchorText(article.children[2])),
    ).toBe(article.children[2])
    // 正文改版找不到锚点 → null（调用方按 ratio 回退）。
    expect(findAnchorElement(container, '不存在的段落文本')).toBeNull()
    expect(findAnchorElement(container, null)).toBeNull()
  })

  it('正文变化后，锚点段落文字未变仍可定位（安全回退语义）', () => {
    const container = document.createElement('div')
    const article = document.createElement('div')
    article.className = 'lumi-reader-article'
    const keep = document.createElement('p')
    keep.textContent = '这段话在正文修订后仍然存在'
    const inserted = document.createElement('p')
    inserted.textContent = '修订时新增的段落'
    article.append(keep, inserted)
    container.appendChild(article)
    expect(findAnchorElement(container, '这段话在正文修订后仍然存在')).toBe(keep)
  })
})
