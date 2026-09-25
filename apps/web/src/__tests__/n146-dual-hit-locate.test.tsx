/** N146 双语命中定位 — collectHitPairLocations 配对定位 + chip 双语上下文。
 *
 * - 译文节点（data-lb-t）不参与偏移计数：overlay 注入后命中仍能定位；
 * - 命中块有配对译文（.lb-pair / nextElementSibling 两种布局）→ 返回
 *   translation；未翻译块 → null；
 * - chip 双语上下文：原文片段（命中词高亮）+ 译文片段并列展示；
 * - 跳转定位到配对：译文节点打上临时高亮（data-lb-hit）。
 */

import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  collectHitPairLocations,
  findPairedTranslation,
  hitSnippet,
  markTranslationHit,
  clearTranslationHit,
  stashSearchHits,
} from '../lib/search-hit-locate'
import { SearchHitsChip } from '../components/SearchHitsChip'
import { annotateBlocks, applyOverlay } from '../lib/translation-blocks'

function buildRoot(): { root: HTMLDivElement; blocks: HTMLElement[] } {
  const root = document.createElement('div')
  // 注意：fixture 不预置 data-lb-index ——「overlay 未激活」用例要求
  // 块未编号；annotateBlocks 由各测试按需调用。
  root.innerHTML =
    '<p>前缀文字 alpha 中段内容。</p>' +
    '<p>第二段 alpha 再次命中。</p>'
  document.body.append(root)
  return { root, blocks: Array.from(root.querySelectorAll('p')) }
}

describe('N146 collectHitPairLocations', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('overlay 未激活：block/translation 为 null，定位与 F072 一致', () => {
    const { root } = buildRoot()
    const text = root.textContent ?? ''
    const { locations, missed } = collectHitPairLocations(root, [
      { offset: text.indexOf('alpha'), term: 'alpha' },
    ])
    expect(missed).toBe(0)
    expect(locations[0]?.range.toString()).toBe('alpha')
    expect(locations[0]?.block).toBeNull()
    expect(locations[0]?.translation).toBeNull()
  })

  it('bilingual overlay：命中块返回配对译文；译文文本不参与偏移计数', () => {
    const { root, blocks } = buildRoot()
    annotateBlocks(root)
    // 对块 0 施加双语 overlay（真实 applyOverlay 路径）。
    applyOverlay(root, { texts: new Map([[0, 'Alpha 译文第一块']]), mode: 'bilingual' })
    // overlay 后全局文本偏移会变化——按原文口径重新计算期望偏移：
    // 原文文本 = 块0 + 块1 顺序（译文被排除在计数之外）。
    const sourceText = blocks.map((b) => b.textContent ?? '').join('')
    const offset = sourceText.indexOf('alpha', sourceText.indexOf('alpha') + 1)
    const { locations, missed } = collectHitPairLocations(root, [
      { offset, term: 'alpha' },
    ])
    expect(missed).toBe(0)
    expect(locations[0]?.block).toBe(blocks[1])
    expect(locations[0]?.translation).toBeNull() // 块 1 未翻译
    // 块 0 的命中带上配对译文。
    const offset0 = sourceText.indexOf('alpha')
    const pairResult = collectHitPairLocations(root, [{ offset: offset0, term: 'alpha' }])
    expect(pairResult.locations[0]?.block).toBe(blocks[0])
    expect(pairResult.locations[0]?.translation?.textContent).toBe('Alpha 译文第一块')
  })

  it('findPairedTranslation：translated（nextElementSibling）布局也命中', () => {
    const { root, blocks } = buildRoot()
    annotateBlocks(root)
    applyOverlay(root, { texts: new Map([[0, '译文（原文隐藏）']]), mode: 'translated' })
    expect(blocks[0].getAttribute('data-lb-hidden')).toBe('1')
    expect(findPairedTranslation(blocks[0])?.textContent).toBe('译文（原文隐藏）')
    expect(findPairedTranslation(blocks[1])).toBeNull()
  })

  it('hitSnippet 截取命中两侧片段并标注截断', () => {
    const text = '0123456789'.repeat(10)
    const snippet = hitSnippet(text, 40, 4, 6)
    expect(snippet.term).toBe(text.slice(40, 44))
    expect(snippet.before).toBe(text.slice(34, 40))
    expect(snippet.after).toBe(text.slice(44, 50))
    expect(snippet.clippedStart).toBe(true)
    expect(snippet.clippedEnd).toBe(true)
    // 边界：命中在开头 → 不截断。
    const head = hitSnippet('alpha 后文', 0, 5, 10)
    expect(head.before).toBe('')
    expect(head.clippedStart).toBe(false)
  })
})

function renderChip(props: {
  entryRef: string
  root: Element | null
  viewMode?: 'original' | 'bilingual' | 'translated'
}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <SearchHitsChip
        entryRef={props.entryRef}
        getRoot={() => props.root}
        detailReady
        viewMode={props.viewMode ?? 'bilingual'}
      />
    </QueryClientProvider>,
  )
}

describe('N146 SearchHitsChip 双语上下文', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    document.body.innerHTML = ''
  })

  it('命中带配对译文 → 双语上下文（原文+译文片段）；跳转标记译文', async () => {
    const { root, blocks } = buildRoot()
    annotateBlocks(root)
    applyOverlay(root, { texts: new Map([[0, 'Alpha 译文第一块']]), mode: 'bilingual' })
    const sourceText = blocks.map((b) => b.textContent ?? '').join('')
    stashSearchHits('e1.dual', [{ offset: sourceText.indexOf('alpha'), term: 'alpha' }])
    renderChip({ entryRef: 'e1.dual', root })

    const context = await screen.findByTestId('dual-hit-context')
    expect(context).toBeInTheDocument()
    // 原文片段含命中词；译文片段展示译文（chip 内的译文 mark）。
    const marks = context.querySelectorAll('mark')
    expect(marks[1]?.textContent).toBe('Alpha 译文第一块')
    expect(blocks[0].parentElement?.querySelector('.lb-translation')?.hasAttribute('data-lb-hit')).toBe(true)
  })

  it('overlay 激活但命中块无译文 → 不显示双语上下文（诚实回退）', async () => {
    const { root, blocks } = buildRoot()
    annotateBlocks(root)
    // 只翻译块 1（第二段）。
    applyOverlay(root, { texts: new Map([[1, '译文二']]), mode: 'bilingual' })
    const sourceText = blocks.map((b) => b.textContent ?? '').join('')
    stashSearchHits('e1.plain', [{ offset: sourceText.indexOf('alpha'), term: 'alpha' }])
    renderChip({ entryRef: 'e1.plain', root })

    expect(await screen.findByText(/命中 1 处/)).toBeInTheDocument()
    expect(screen.queryByTestId('dual-hit-context')).toBeNull()
  })

  it('markTranslationHit / clearTranslationHit 幂等清理', () => {
    const el = document.createElement('div')
    markTranslationHit(el)
    expect(el.getAttribute('data-lb-hit')).toBe('1')
    expect(el.style.backgroundColor).toContain('var(--lumi-accent-soft)')
    clearTranslationHit(el)
    expect(el.hasAttribute('data-lb-hit')).toBe(false)
    expect(el.style.backgroundColor).toBe('')
  })
})
