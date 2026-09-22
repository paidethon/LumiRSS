/** 阅读位置恢复（pool #01）——每篇文章（ItemRef）独立记忆滚动位置。
 *
 * 存储：localStorage 单键 `lumirss-reading-positions`（客户端自有状态，
 * 不进设置同步、不碰已读状态）；结构 v1 = LRU 有界（200 篇）：
 *   { v: 1, order: string[], byRef: Record<string, ReadingPosition> }
 *
 * 位置 = ratio（0..1，滚动比例）+ anchorText（视口顶部附近段落的文本
 * 前缀，用于正文高度变化后的二次定位）。恢复时锚点优先、ratio 回退：
 * 找得到锚点就贴段落，找不到按比例落点——两者都只会落在**本篇文章**
 * 内，绝不会跳到其他文章。
 *
 * 几何计算（getBoundingClientRect / scrollTop）留在 Reader 组件；本模块
 * 只做可测试的存储与文本锚点匹配。 */

export interface ReadingPosition {
  /** 0..1；scrollHeight 不可用时为 0。 */
  ratio: number
  /** 视口上方最近段落的前缀（规范化空白后前 64 字符），可为 null。 */
  anchorText: string | null
  savedAt: string
}

const KEY = 'lumirss-reading-positions'
const VERSION = 1
const CAP = 200
const ANCHOR_LENGTH = 64

interface PositionMap {
  v: number
  order: string[]
  byRef: Record<string, ReadingPosition>
}

function emptyMap(): PositionMap {
  return { v: VERSION, order: [], byRef: {} }
}

function isValidPosition(value: unknown): value is ReadingPosition {
  if (typeof value !== 'object' || value === null) return false
  const v = value as Record<string, unknown>
  return (
    typeof v.ratio === 'number' &&
    Number.isFinite(v.ratio) &&
    (v.anchorText === null || typeof v.anchorText === 'string') &&
    typeof v.savedAt === 'string'
  )
}

function readMap(): PositionMap {
  try {
    const raw = window.localStorage.getItem(KEY)
    if (raw === null) return emptyMap()
    const parsed = JSON.parse(raw) as unknown
    if (typeof parsed !== 'object' || parsed === null) return emptyMap()
    const candidate = parsed as Partial<PositionMap>
    if (candidate.v !== VERSION || !Array.isArray(candidate.order)) {
      return emptyMap()
    }
    const byRef: Record<string, ReadingPosition> = {}
    const order: string[] = []
    for (const ref of candidate.order) {
      if (typeof ref !== 'string') continue
      const position = (candidate.byRef ?? {})[ref]
      if (isValidPosition(position)) {
        byRef[ref] = position
        order.push(ref)
      }
    }
    return { v: VERSION, order, byRef }
  } catch {
    // 损坏的 JSON / 隐私模式拒绝写入：视为无历史，绝不让阅读器崩掉。
    return emptyMap()
  }
}

function writeMap(map: PositionMap): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(map))
  } catch {
    // 配额满 / 隐私模式：位置记忆是尽力而为的增强，静默放弃。
  }
}

export function saveReadingPosition(
  entryRef: string,
  position: ReadingPosition,
): void {
  const anchor =
    position.anchorText !== null ? position.anchorText.trim() : ''
  const clamped: ReadingPosition = {
    ...position,
    ratio: Math.min(1, Math.max(0, position.ratio)),
    anchorText: anchor !== '' ? anchor.slice(0, ANCHOR_LENGTH) : null,
  }
  const map = readMap()
  const existing = map.order.indexOf(entryRef)
  if (existing !== -1) map.order.splice(existing, 1)
  map.order.push(entryRef)
  map.byRef[entryRef] = clamped
  while (map.order.length > CAP) {
    const evicted = map.order.shift()
    if (evicted !== undefined) delete map.byRef[evicted]
  }
  writeMap(map)
}

export function loadReadingPosition(entryRef: string): ReadingPosition | null {
  const map = readMap()
  return map.byRef[entryRef] ?? null
}

/** 段落锚点文本：规范化连续空白后取前缀，保证同一段落的重复捕获稳定。 */
export function captureAnchorText(element: Element | null): string | null {
  if (element === null) return null
  const text = (element.textContent ?? '').replace(/\s+/g, ' ').trim()
  if (text === '') return null
  return text.slice(0, ANCHOR_LENGTH)
}

/** 在当前正文中找锚点段落（文本前缀精确匹配）。正文改版导致找不到时
 * 返回 null，调用方按 ratio 回退——安全降级，不误跳。 */
export function findAnchorElement(
  container: ParentNode,
  anchorText: string | null,
): Element | null {
  if (anchorText === null) return null
  const candidates = container.querySelectorAll(
    [
      '.lumi-reader-article p',
      '.lumi-reader-article li',
      '.lumi-reader-article pre',
      '.lumi-reader-article blockquote',
      '.lumi-reader-article h1',
      '.lumi-reader-article h2',
      '.lumi-reader-article h3',
      '.lumi-reader-article h4',
      '.lumi-reader-article h5',
      '.lumi-reader-article h6',
    ].join(', '),
  )
  for (const element of candidates) {
    if (captureAnchorText(element) === anchorText) return element
  }
  return null
}

/** 清空全部阅读位置（O157 换账号防串号：登出/登录统一调用）。
 * 位置记忆虽是本设备数据，但「读到哪」是用户内容足迹——换号即清。 */
export function clearReadingPositions(): void {
  try {
    window.localStorage.removeItem(KEY)
  } catch {
    // ignore
  }
}

export function forgetReadingPositionsForTest(): void {
  clearReadingPositions()
}
