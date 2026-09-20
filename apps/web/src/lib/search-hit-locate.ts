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
