/** translation-scope — N087 按章节/范围翻译 + 有界分批派发队列。
 *
 * - 翻译范围：全文（默认）/ 当前章节 / 从当前块到结尾；块子集来自与
 *   其他功能同一套 data-lb-index 编号块（translation-blocks.annotateBlocks）；
 * - 章节划分与 lib/article-chapters（N051）同规则：.article-content 的
 *   直系 h2/h3/h4 为界，同级或更高级标题开新章节；首章之前的块并入
 *   第一章节（containingChapterId 同规则）；标题本身也是可翻译块；
 * - 预计字符量 = 所选块源文本长度之和（客户端可算，诚实近似）；
 * - 派发队列：把所选块切成有界批次顺序发送（每批 ≤8 块且 ≤6000 字符，
 *   远小于 BFF 的批次上限）；取消 = 中止当前 fetch 且不再派发后续
 *   批次 —— 是真的停止请求，不只是隐藏 UI。
 */

import type { TranslationSegmentBlockInput } from '../api/client'
import { generateTranslationSegments } from '../api/client'
import { normalizedBlockText, type ArticleBlock } from './translation-blocks'

export type TranslationScope = 'all' | 'chapter' | 'toEnd'

export const TRANSLATION_SCOPE_LABELS: Record<TranslationScope, string> = {
  all: '全文',
  chapter: '当前章节',
  toEnd: '从当前块到结尾',
}

/** 一个章节区间：headingIndex = 章节标题块的 data-lb-index（无标题
 * 的全文区间为 null）；blockIndexes = 该章节全部可翻译块（含标题）。 */
export interface ChapterRange {
  headingIndex: number | null
  blockIndexes: number[]
}

const CHAPTER_HEADING_RE = /^H[234]$/

/** 从已编号正文中推导章节区间（与 article-chapters 的划分一致）。
 * 块按其顶层直系祖先聚组（嵌套块如 figcaption 归属 figure），因此
 * 不受嵌套结构影响。无标题 → 单一全文区间（章节选项退化为全文）。 */
export function collectChapterRanges(root: HTMLElement): ChapterRange[] {
  const content = root.querySelector('.article-content') ?? root
  const indexed = Array.from(
    content.querySelectorAll<HTMLElement>('[data-lb-index]'),
  )
  if (indexed.length === 0) return []
  const topLevelOf = (el: Element): Element => {
    let node: Element = el
    while (
      node.parentElement !== null &&
      node.parentElement !== content &&
      node.parentElement !== root
    ) {
      node = node.parentElement
    }
    return node
  }
  // 顶层子元素 → 按文档顺序聚合的块 index 列表。
  const groups: Array<{ el: Element; indexes: number[] }> = []
  const byElement = new Map<Element, number[]>()
  for (const el of indexed) {
    const top = topLevelOf(el)
    let list = byElement.get(top)
    if (list === undefined) {
      list = []
      byElement.set(top, list)
      groups.push({ el: top, indexes: list })
    }
    list.push(Number(el.getAttribute('data-lb-index')))
  }
  const ranges: ChapterRange[] = []
  const pending: number[] = [] // 首章之前的块（并入第一章节）
  let current: ChapterRange | null = null
  let level = 0
  for (const { el, indexes } of groups) {
    if (CHAPTER_HEADING_RE.test(el.tagName)) {
      const headingLevel = Number(el.tagName[1])
      if (current === null || headingLevel <= level) {
        current = { headingIndex: indexes[0] ?? null, blockIndexes: [...indexes] }
        ranges.push(current)
        level = headingLevel
        if (ranges.length === 1 && pending.length > 0) {
          current.blockIndexes.unshift(...pending.splice(0))
        }
        continue
      }
    }
    if (current === null) pending.push(...indexes)
    else current.blockIndexes.push(...indexes)
  }
  if (ranges.length === 0) {
    return [
      {
        headingIndex: null,
        blockIndexes: indexed.map((el) => Number(el.getAttribute('data-lb-index'))),
      },
    ]
  }
  return ranges
}

export interface ScopeSelection {
  scope: TranslationScope
  blocks: ArticleBlock[]
  /** 预计字符量（所选块源文本长度之和）。 */
  chars: number
}

/** 依据范围与上下文（章节区间 + 当前可见块）选出块子集。
 * - chapter：当前块所在章节（含标题）；无区间匹配 → 第一章节；
 * - toEnd：当前块（含）到结尾；无可见块 → 全文（诚实回退）。
 * 未选中的块绝不出现在结果里（也就绝不产生远程请求）。 */
export function selectScopeBlocks(
  blocks: ArticleBlock[],
  scope: TranslationScope,
  ctx: {
    ranges?: ChapterRange[] | null
    currentBlockIndex?: number | null
  } = {},
): ScopeSelection {
  const select = (indexes: Set<number> | null): ArticleBlock[] =>
    indexes === null ? blocks : blocks.filter((b) => indexes.has(b.index))
  if (scope === 'all' || blocks.length === 0) {
    return { scope, blocks, chars: estimateChars(blocks) }
  }
  const currentIndex =
    ctx.currentBlockIndex ?? null
  if (scope === 'toEnd') {
    const start =
      currentIndex !== null && blocks.some((b) => b.index === currentIndex)
        ? currentIndex
        : blocks[0].index
    const selected = blocks.filter((b) => b.index >= start)
    return { scope, blocks: selected, chars: estimateChars(selected) }
  }
  // chapter
  const ranges = ctx.ranges ?? []
  const ordered = [...blocks].sort((a, b) => a.index - b.index)
  const current =
    currentIndex !== null ? ordered.find((b) => b.index === currentIndex) ?? null : null
  let target: ChapterRange | null = null
  if (current !== null) {
    target =
      ranges.find((range) => range.blockIndexes.includes(current.index)) ?? null
  }
  if (target === null && ranges.length > 0) target = ranges[0]
  const selected = select(
    target === null ? null : new Set(target.blockIndexes),
  )
  return {
    scope,
    blocks: selected.length > 0 ? selected : blocks,
    chars: estimateChars(selected.length > 0 ? selected : blocks),
  }
}

/** 预计字符量（归一化后源文本长度之和；客户端可算的诚实近似）。 */
export function estimateChars(blocks: ArticleBlock[]): number {
  return blocks.reduce((total, block) => total + normalizedBlockText(block.text).length, 0)
}

// -- 有界分批派发队列 ---------------------------------------------------------

export const QUEUE_MAX_BLOCKS = 8
export const QUEUE_MAX_CHARS = 6000

/** 把块列表切成有界批次（每批 ≤maxBlocks 且 ≤maxChars；贪心装箱）。 */
export function chunkTranslationBlocks<T extends { text: string }>(
  blocks: T[],
  maxBlocks: number = QUEUE_MAX_BLOCKS,
  maxChars: number = QUEUE_MAX_CHARS,
): T[][] {
  const chunks: T[][] = []
  let current: T[] = []
  let currentChars = 0
  for (const block of blocks) {
    const length = normalizedBlockText(block.text).length
    if (current.length > 0 && (current.length >= maxBlocks || currentChars + length > maxChars)) {
      chunks.push(current)
      current = []
      currentChars = 0
    }
    current.push(block)
    currentChars += length
  }
  if (current.length > 0) chunks.push(current)
  return chunks
}

export interface TranslationQueueResult {
  cancelled: boolean
  dispatched: number
}

/** 顺序派发队列：取消后不再发送任何后续批次（当前批次的 fetch 由
 * AbortSignal 中止）。每批完成即由调用方刷新缓存（增量可见）。 */
export class TranslationQueue {
  private controller: AbortController | null = null
  private readonly send: (
    blocks: TranslationSegmentBlockInput[],
    signal: AbortSignal,
  ) => Promise<void>

  constructor(
    send: (
      blocks: TranslationSegmentBlockInput[],
      signal: AbortSignal,
    ) => Promise<void>,
  ) {
    this.send = send
  }

  /** 中止在途批次并停止派发（幂等）。 */
  cancel(): void {
    this.controller?.abort()
  }

  get running(): boolean {
    return this.controller !== null && !this.controller.signal.aborted
  }

  async run(blocks: ArticleBlock[]): Promise<TranslationQueueResult> {
    this.controller?.abort()
    const controller = new AbortController()
    this.controller = controller
    let dispatched = 0
    for (const chunk of chunkTranslationBlocks(blocks)) {
      if (controller.signal.aborted) {
        return { cancelled: true, dispatched }
      }
      dispatched += 1 // 已发出的请求计数（在途中被取消也算发出过）
      try {
        await this.send(
          chunk.map((b) => ({ index: b.index, text: b.text })),
          controller.signal,
        )
      } catch (error) {
        if (controller.signal.aborted) {
          return { cancelled: true, dispatched }
        }
        throw error
      }
    }
    return { cancelled: controller.signal.aborted, dispatched }
  }
}

/** Reader 用的默认 send：走统一的 BFF generate 端点（带中止信号）。 */
export function defaultQueueSend(
  entryRef: string,
): (blocks: TranslationSegmentBlockInput[], signal: AbortSignal) => Promise<void> {
  return (blocks, signal) =>
    generateTranslationSegments(entryRef, blocks, { signal }).then(() => undefined)
}
