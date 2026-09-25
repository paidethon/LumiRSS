/** search-hit-locate — F072 命中定位：搜索命中的正文偏移 → 打开文章后
 * 定位/循环高亮。
 *
 * - 暂存：SearchPage 打开条目前把 matchPositions 存 sessionStorage
 *   （有界：最近 5 篇）；Reader 挂载后取用（读取即清除）；
 * - 定位：TreeWalker 累计文本偏移找到命中所在的文本节点与内偏移，
 *   并校验该处文本确实以命中词开头（casefold，与 F072 服务端口径
 *   一致）——任何一处无法定位/校验失败 → degraded（原文已变化，
 *   不跳转，诚实降级）；
 * - 高亮：Range + 选区（不改动 DOM 结构）。 */

export interface SearchHit {
  offset: number
  term: string
}

const STORAGE_KEY = 'lumirss-search-hits'
const MAX_STASHED = 5

function readMap(): Record<string, SearchHit[]> {
  if (typeof sessionStorage === 'undefined') return {}
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (raw === null) return {}
    const parsed = JSON.parse(raw)
    return typeof parsed === 'object' && parsed !== null ? (parsed as Record<string, SearchHit[]>) : {}
  } catch {
    return {}
  }
}

function writeMap(map: Record<string, SearchHit[]>): void {
  if (typeof sessionStorage === 'undefined') return
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(map))
  } catch {
    /* 写失败不影响本会话 */
  }
}

export function stashSearchHits(entryRef: string, hits: SearchHit[]): void {
  if (!entryRef || hits.length === 0) return
  const map = readMap()
  map[entryRef] = hits
  const keys = Object.keys(map)
  while (keys.length > MAX_STASHED) {
    const oldest = keys.shift()
    if (oldest === undefined) break
    delete map[oldest]
  }
  writeMap(map)
}

export function takeSearchHits(entryRef: string): SearchHit[] {
  const map = readMap()
  const hits = map[entryRef]
  if (hits === undefined) return []
  delete map[entryRef]
  writeMap(map)
  return Array.isArray(hits) ? hits : []
}

export interface HitLocateResult {
  ranges: Range[]
  /** 无法定位/校验失败的命中数（正文已变化或尚未渲染完）。 */
  missed: number
}

function normChar(value: string): string {
  return value.toLowerCase()
}

/** 在 root 内为每个命中构建 Range（区间不交叉、不修改 DOM）。 */
export function collectHitRanges(root: Element, hits: SearchHit[]): HitLocateResult {
  const sorted = [...hits].sort((a, b) => a.offset - b.offset)
  if (sorted.length === 0 || root === null) {
    return { ranges: [], missed: 0 }
  }
  // 预收集文本节点（node, start, length）
  const nodes: { node: Text; start: number; length: number }[] = []
  let total = 0
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  for (
    let node = walker.nextNode();
    node !== null;
    node = walker.nextNode()
  ) {
    const text = node as Text
    const length = text.data.length
    nodes.push({ node: text, start: total, length })
    total += length
  }
  const ranges: Range[] = []
  let missed = 0
  for (const hit of sorted) {
    if (hit.offset < 0 || hit.offset + hit.term.length > total) {
      missed += 1
      continue
    }
    // 找到偏移所在文本节点
    let container: Text | null = null
    let localOffset = 0
    for (const entry of nodes) {
      if (hit.offset >= entry.start && hit.offset <= entry.start + entry.length) {
        container = entry.node
        localOffset = hit.offset - entry.start
        break
      }
    }
    if (container === null) {
      missed += 1
      continue
    }
    // 校验该处文本以命中词开头（casefold 逐字符比较）
    const slice = container.data.slice(localOffset, localOffset + hit.term.length)
    const matches = slice.length === hit.term.length &&
      [...slice].every((ch, i) => normChar(ch) === normChar(hit.term[i] ?? ''))
    if (!matches) {
      missed += 1
      continue
    }
    const range = document.createRange()
    range.setStart(container, localOffset)
    range.setEnd(container, localOffset + hit.term.length)
    ranges.push(range)
  }
  return { ranges, missed }
}

/** 选中一个 Range（视觉高亮 + 滚动到可见）。 */
export function selectRange(range: Range): void {
  const selection = typeof window !== 'undefined' ? window.getSelection() : null
  if (selection === null) return
  selection.removeAllRanges()
  selection.addRange(range)
  const element =
    range.startContainer instanceof Element
      ? range.startContainer
      : range.startContainer.parentElement
  if (typeof range.getBoundingClientRect === 'function') {
    const rect = range.getBoundingClientRect()
    if (rect.height > 0) return // 已在视觉区内的选区不额外滚动
  }
  element?.scrollIntoView?.({ block: 'center' })
}

// ---- N146：双语命中定位（overlay 激活时的原文+译文配对定位） ----

export interface HitPairLocation {
  range: Range
  /** 命中所在的内容块（data-lb-index 标注块）；overlay 未激活/块未编号
   * 时为 null（此时等同 F072 纯定位行为）。 */
  block: HTMLElement | null
  /** 该块的配对译文节点（.lb-translation）；该块无译文时为 null。 */
  translation: HTMLElement | null
  /** 命中在其块文本内的偏移（原文片段截取用）。 */
  blockOffset: number
}

/** 找到一个内容块的配对译文节点（applyOverlay 的两种布局都覆盖）：
 * - bilingual 顶层块：block 被包进 .lb-pair，译文是 pair 里的
 *   .lb-translation；
 * - translated / 嵌套块：译文节点紧随 block 之后（nextElementSibling）。 */
export function findPairedTranslation(block: Element): HTMLElement | null {
  const pair = block.closest('.lb-pair')
  if (pair !== null) {
    const inside = pair.querySelector<HTMLElement>('.lb-translation')
    if (inside !== null) return inside
  }
  const next = block.nextElementSibling
  return next !== null && next.classList.contains('lb-translation')
    ? (next as HTMLElement)
    : null
}

/** 文本节点是否属于注入的译文（定位偏移必须只对原文文本计数，否则
 * overlay 插入的译文会把后续命中偏移全部推偏）。 */
function isTranslationText(node: Node): boolean {
  const element = node.parentElement
  return element !== null && element.closest('[data-lb-t="1"]') !== null
}

/** F072 的配对增强版：为每个命中同时返回 Range + 所在块 + 配对译文 +
 * 块内偏移。overlay 未激活时 block/translation 为 null，定位行为与
 * collectHitRanges 完全一致（偏移口径相同：仅原文文本参与计数）。 */
export function collectHitPairLocations(
  root: Element,
  hits: SearchHit[],
): { locations: (HitPairLocation | null)[]; missed: number } {
  const sorted = [...hits].sort((a, b) => a.offset - b.offset)
  if (sorted.length === 0 || root === null) {
    return { locations: [], missed: 0 }
  }
  const nodes: { node: Text; start: number; length: number }[] = []
  let total = 0
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) =>
      isTranslationText(node) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  })
  for (
    let node = walker.nextNode();
    node !== null;
    node = walker.nextNode()
  ) {
    const text = node as Text
    nodes.push({ node: text, start: total, length: text.data.length })
    total += text.data.length
  }
  const locations: (HitPairLocation | null)[] = []
  let missed = 0
  for (const hit of sorted) {
    if (hit.offset < 0 || hit.offset + hit.term.length > total) {
      missed += 1
      continue
    }
    let container: Text | null = null
    let localOffset = 0
    for (const entry of nodes) {
      if (hit.offset >= entry.start && hit.offset <= entry.start + entry.length) {
        container = entry.node
        localOffset = hit.offset - entry.start
        break
      }
    }
    if (container === null) {
      missed += 1
      continue
    }
    const slice = container.data.slice(localOffset, localOffset + hit.term.length)
    const matches = slice.length === hit.term.length &&
      [...slice].every((ch, i) => normChar(ch) === normChar(hit.term[i] ?? ''))
    if (!matches) {
      missed += 1
      continue
    }
    const range = document.createRange()
    range.setStart(container, localOffset)
    range.setEnd(container, localOffset + hit.term.length)
    // 块关联 + 配对译文 + 块内偏移（对块内文本重新累计，覆盖同一
    // 「跳过译文节点」口径）。
    const host =
      container.parentElement?.closest<HTMLElement>('[data-lb-index]') ?? null
    let translation: HTMLElement | null = null
    let blockOffset = 0
    if (host !== null) {
      translation = findPairedTranslation(host)
      for (const entry of nodes) {
        if (entry.node === container) break
        if (host.contains(entry.node)) blockOffset += entry.length
      }
    }
    locations.push({ range, block: host, translation, blockOffset })
  }
  return { locations, missed }
}

export interface HitSnippet {
  before: string
  term: string
  after: string
  clippedStart: boolean
  clippedEnd: boolean
}

/** 命中两侧的纯文本片段（N146 双语命中上下文；不对 HTML 转义——
 * 调用方以 text 渲染）。 */
export function hitSnippet(
  text: string,
  offset: number,
  termLength: number,
  radius = 24,
): HitSnippet {
  const safeOffset = Math.max(0, Math.min(offset, Math.max(0, text.length)))
  const start = Math.max(0, safeOffset - radius)
  const end = Math.min(text.length, safeOffset + termLength + radius)
  return {
    before: text.slice(start, safeOffset),
    term: text.slice(safeOffset, safeOffset + termLength),
    after: text.slice(safeOffset + termLength, end),
    clippedStart: start > 0,
    clippedEnd: end < text.length,
  }
}

const TRANSLATION_HIT_ATTR = 'data-lb-hit'

/** 双语定位：给配对译文加临时高亮（语义 token 内联样式；不动结构）。 */
export function markTranslationHit(el: HTMLElement): void {
  el.setAttribute(TRANSLATION_HIT_ATTR, '1')
  el.style.backgroundColor = 'var(--lumi-accent-soft)'
  el.style.scrollMarginTop = '3rem'
}

/** 清除上一个译文命中高亮。 */
export function clearTranslationHit(el: HTMLElement): void {
  el.removeAttribute(TRANSLATION_HIT_ATTR)
  el.style.removeProperty('background-color')
  el.style.removeProperty('scroll-margin-top')
}
