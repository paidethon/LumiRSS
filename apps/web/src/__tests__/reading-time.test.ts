/** reading-time 测试 — 0012 Gate 5（AC8：中英混排稳定计算）。 */

import { describe, expect, it } from 'vitest'
import {
  CJK_CHARS_PER_MINUTE,
  LATIN_WORDS_PER_MINUTE,
  estimateReadingTime,
  formatReadingTime,
  textFromHtml,
} from '../lib/reading-time'

describe('estimateReadingTime — 纯中文', () => {
  it('按中文速度计算', () => {
    // 恰好 300 字 → 1 分钟
    const text = '字'.repeat(CJK_CHARS_PER_MINUTE)
    expect(estimateReadingTime(text)).toEqual({
      minutes: 1,
      cjkCharacters: CJK_CHARS_PER_MINUTE,
      latinWords: 0,
    })
  })

  it('600 字 → 2 分钟（向上取整）', () => {
    const text = '字'.repeat(CJK_CHARS_PER_MINUTE * 2)
    expect(estimateReadingTime(text).minutes).toBe(2)
  })

  it('301 字 → 2 分钟（ceil）', () => {
    const text = '字'.repeat(CJK_CHARS_PER_MINUTE + 1)
    expect(estimateReadingTime(text).minutes).toBe(2)
  })
})

describe('estimateReadingTime — 纯英文', () => {
  it('按英文词速计算', () => {
    const words = Array.from({ length: LATIN_WORDS_PER_MINUTE }, () => 'word').join(' ')
    const est = estimateReadingTime(words)
    expect(est.latinWords).toBe(LATIN_WORDS_PER_MINUTE)
    expect(est.minutes).toBe(1)
  })

  it('撇号词算一个词', () => {
    expect(estimateReadingTime("don't stop").latinWords).toBe(2)
  })
})

describe('estimateReadingTime — 中英混排（AC8）', () => {
  it('两种速度加权', () => {
    // 150 中文字（0.5min）+ 110 英文词（0.5min）= 1 分钟
    const text = '字'.repeat(150) + ' ' + Array.from({ length: 110 }, () => 'word').join(' ')
    const est = estimateReadingTime(text)
    expect(est.cjkCharacters).toBe(150)
    expect(est.latinWords).toBe(110)
    expect(est.minutes).toBe(1)
  })

  it('混排明显比纯英文 word count 合理（中文长文不是 0 词）', () => {
    const chineseArticle = '这是一篇很长很长的中文文章'.repeat(50) // 13 字 × 50 = 650
    expect(estimateReadingTime(chineseArticle).latinWords).toBe(0)
    expect(estimateReadingTime(chineseArticle).cjkCharacters).toBe(650)
    expect(estimateReadingTime(chineseArticle).minutes).toBe(3) // 650/300 = 2.17 → ceil
  })

  it('空文本 → 最短 1 分钟', () => {
    expect(estimateReadingTime('').minutes).toBe(1)
  })

  it('标点/数字不计入（避免双重计费）', () => {
    const est = estimateReadingTime('12345 67890，。！？')
    expect(est.cjkCharacters).toBe(0)
    expect(est.latinWords).toBe(0)
    expect(est.minutes).toBe(1)
  })

  it('结果稳定（同输入同输出）', () => {
    const text = '混合 mix 内容 content 与 with 中文 chinese'
    expect(estimateReadingTime(text)).toEqual(estimateReadingTime(text))
  })
})

describe('formatReadingTime — 展示格式', () => {
  it('非常短 → < 1 分钟', () => {
    expect(formatReadingTime('短文')).toBe('< 1 分钟')
    expect(formatReadingTime('')).toBe('< 1 分钟')
  })

  it('正常 → 约 N 分钟', () => {
    expect(formatReadingTime('字'.repeat(CJK_CHARS_PER_MINUTE))).toBe('约 1 分钟')
    expect(formatReadingTime('字'.repeat(CJK_CHARS_PER_MINUTE * 3))).toBe('约 3 分钟')
  })

  it('不出现小数', () => {
    const out = formatReadingTime('字'.repeat(700))
    expect(out).not.toMatch(/0\.\d+/)
    expect(out).toBe('约 3 分钟')
  })
})

describe('textFromHtml — HTML → 纯文本', () => {
  it('去标签、归一空格', () => {
    expect(textFromHtml('<p>hello</p><p>world</p>')).toBe('hello world')
    expect(textFromHtml('<p>a<b>b</b>c</p>')).toBe('abc')
  })

  it('script/style 内容不计入', () => {
    expect(textFromHtml('<p>text</p><script>alert(1)</script><style>.x{}</style>')).toBe('text')
  })
})
