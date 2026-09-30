/**
 * FIX-082 — 中文长标题 / 英文长单词 / URL 不撑破容器基线守卫
 * （source-level 断言，风格同 fix-132-content-overflow）。
 *
 * 分层现状：
 * - 正文（.article-content）：index.css word-break: break-word 兜底 +
 *   行内代码 overflow-wrap: anywhere（0007）——长 token 不撑破阅读列；
 * - 列表行（EntryRow/EntryCard）：min-w-0 祖先链 + 单行 truncate /
 *   line-clamp；截断处完整文本经 title 属性（EntryRow 标题 tooltip）
 *   与 Reader 全文视图可达；
 * - 阅读页强标题（ReaderHeader h1）：【本批真修】原缺 break-words，
 *   标题本身是长 URL/长英文单词（CJK 天然可断行，不受影响）时会把
 *   阅读列横向撑破——补 break-words（overflow-wrap: break-word），
 *   与正文兜底同一档；
 * - URL 直出位（ProvenanceCard 等）：break-all 收进自身容器。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const read = (rel: string): string => readFileSync(resolve(__dirname, '..', rel), 'utf-8')

const indexCss = read('index.css')
const entryRow = read('components/EntryRow.tsx')
const entryCard = read('components/EntryCard.tsx')
const readerHeader = read('components/ReaderHeader.tsx')
const provenanceCard = read('components/ProvenanceCard.tsx')

/** 取行首锚定 selector 的 CSS 块体（同 fix-132 cssBlock）。 */
function cssBlock(css: string, selector: string): string | null {
  const idx = css.indexOf(`\n${selector}`)
  if (idx === -1) return null
  const open = css.indexOf('{', idx)
  const close = css.indexOf('}', open)
  if (open === -1 || close === -1) return null
  return css.slice(open + 1, close)
}

describe('FIX-082: 正文长 token 兜底（index.css）', () => {
  it('.article-content word-break: break-word（长英文单词/URL 不撑破阅读列）', () => {
    expect(cssBlock(indexCss, '.article-content')).toContain('word-break: break-word')
  })

  it('行内代码 overflow-wrap: anywhere（0007：长 token 不撑破手机屏）', () => {
    expect(cssBlock(indexCss, '.article-content code')).toContain('overflow-wrap: anywhere')
  })
})

describe('FIX-082: 列表行 min-w-0 + 截断且完整文本可达', () => {
  it('EntryRow：标题按钮 min-w-0 + lg:truncate，title 属性保留全文', () => {
    expect(entryRow).toMatch(/'min-w-0 rounded-\[var\(--lumi-radius-md\)\] text-left text-sm lg:truncate'/)
    expect(entryRow).toContain('title={item.title}')
  })

  it('EntryCard：内容列 min-w-0 flex-1，标题 line-clamp-3（多行截断）', () => {
    expect(entryCard).toMatch(/flex min-w-0 flex-1 flex-col gap-1\.5/)
    expect(entryCard).toMatch(/line-clamp-3/)
  })

  it('ProvenanceCard：URL 直出位 min-w-0 + break-all（自身容器内换行）', () => {
    expect(provenanceCard).toMatch(/min-w-0 break-all/)
  })
})

describe('FIX-082: 阅读页强标题（本批真修点）', () => {
  it('ReaderHeader h1 带 break-words：标题为长 URL/长单词时不撑破阅读列', () => {
    const start = readerHeader.indexOf('<h1')
    expect(start, 'ReaderHeader 强标题 h1 应存在').toBeGreaterThan(-1)
    const h1 = readerHeader.slice(start, readerHeader.indexOf('>', start))
    expect(h1, 'h1 应含 break-words（overflow-wrap: break-word）').toContain('break-words')
  })
})
