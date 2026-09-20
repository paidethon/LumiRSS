/** annotations — F20 正文高亮/批注（锚点模型 + 设备本地存储）。
 *
 * 设计要点：
 * - BFF 无批注端点，存储用 localStorage key `lumirss-annotations`
 *   （JSON 数组，条目自带 entryRef 字段按其索引）。**明确是设备本地
 *   数据，不跨设备同步，也不写回 Obsidian vault（Lumi 的 vault 只读）**。
 * - 锚点模型借鉴 W3C Web Annotation 的 TextQuoteSelector（prefix/exact/
 *   suffix，inspired，独立简化实现）：正文变化后按「prefix+exact+suffix」
 *   定位，找不到退化 exact，再找不到判定锚点失效（诚实提示，不假装命中）。
 * - contentVersion 是简化的稳定指纹（正文长度 + 首 32 字符 hash），
 *   用于廉价检测「正文大概率已变化」，不做精确 diff。
 */

// ---- 模型 ----

/** 批注颜色三档（高亮底色 + 卡片色点共用） */
export type AnnotationColor = 'yellow' | 'green' | 'pink'

export const ANNOTATION_COLORS: readonly AnnotationColor[] = ['yellow', 'green', 'pink']

/** 文本引文锚点（W3C TextQuoteSelector 简化版） */
export interface AnnotationAnchor {
  /** 选区前文（最多 24 字符） */
  prefix: string
  /** 选区文本（原样） */
  exact: string
  /** 选区后文（最多 24 字符） */
  suffix: string
}

/** 一条批注（设备本地） */
export interface Annotation {
  id: string
  entryRef: string
  color: AnnotationColor
  /** 用户备注（可为空串 = 纯高亮） */
  note: string
  anchor: AnnotationAnchor
  createdAt: number
  /** 正文指纹（长度 + 首 32 字符 hash），检测锚点可能失效 */
  contentVersion: string
}

/** createAnchor 结果：锚点 + 选区文本（列表摘录直接用 exact） */
export interface CreatedAnchor {
  text: string
  anchor: AnnotationAnchor
}

// ---- 常量 ----

export const ANNOTATIONS_STORAGE_KEY = 'lumirss-annotations'

/** 前后文取样长度（字符） */
export const ANCHOR_CONTEXT_CHARS = 24

// ---- 正文指纹 ----

/** FNV-1a 32 位 hash（十六进制）。纯函数、跨会话稳定（不用 crypto
 *  随机——指纹要的是确定性，不是安全性）。 */
export function hashText(text: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return (h >>> 0).toString(16).padStart(8, '0')
}

/** 正文版本指纹：`长度:hash(首32字符)`。 */
export function computeContentVersion(text: string): string {
  return `${text.length}:${hashText(text.slice(0, 32))}`
}

// ---- 正文文本提取（排除本功能注入的覆盖层） ----

/** 批注卡列表 / 浮层等注入节点上的标记（这些节点的文本不参与
 *  锚点计算，避免「批注摘录污染正文对照文本」导致错位）。 */
const OVERLAY_SELECTOR = '[data-lumi-annotations-overlay="true"]'

/** 正文对照文本 = 容器 textContent 去掉本功能注入的覆盖层。
 *  用克隆剥离实现（不改动真实 DOM）。 */
export function articleText(container: HTMLElement): string {
  const clone = container.cloneNode(true) as HTMLElement
  for (const el of clone.querySelectorAll(OVERLAY_SELECTOR)) el.remove()
  return clone.textContent ?? ''
}

// ---- 锚点创建 / 解析（纯逻辑，jsdom 可测） ----

function clampSlice(text: string, start: number, end: number): string {
  return text.slice(Math.max(0, start), Math.max(0, end))
}

/** 从选区创建锚点：取选区文本 + 前后各 24 字符上下文
 *  （上下文对照 container 的全文文本，跨文本节点拼接）。
 *  选区为空 / 容器不含选区文本时返回 null（调用方提示，不静默）。 */
export function createAnchor(container: HTMLElement, range: Range): CreatedAnchor | null {
  const text = range.toString()
  if (text.trim() === '') return null

  // 选区起点前的全部正文文本（容器起点 → 选区起点），尾部 24 字符即 prefix。
  // 覆盖层注入在容器末尾，位于选区之后，天然不会混入 prefix。
  const before = document.createRange()
  before.setStart(container, 0)
  before.setEnd(range.startContainer, range.startOffset)
  const prefixRaw = before.toString()

  const full = articleText(container)
  const startIndex = prefixRaw.length
  const suffixRaw = clampSlice(full, startIndex + text.length, startIndex + text.length + ANCHOR_CONTEXT_CHARS)

  return {
    text,
    anchor: {
      prefix: clampSlice(prefixRaw, prefixRaw.length - ANCHOR_CONTEXT_CHARS, prefixRaw.length),
      exact: text,
      suffix: suffixRaw,
    },
  }
}

/** 锚点命中区间（articleText 内的 [start, end) 下标）。 */
export interface AnchorHit {
  start: number
  end: number
}

/** 在正文中解析锚点：优先 prefix+exact+suffix 整体匹配（抗重复段落），
 *  找不到退化 exact，再找不到返回 null = 锚点失效（调用方诚实提示）。 */
export function resolveAnchor(
  container: HTMLElement,
  anchor: AnnotationAnchor,
): AnchorHit | null {
  const full = articleText(container)
  if (anchor.exact === '') return null

  const withContext = `${anchor.prefix}${anchor.exact}${anchor.suffix}`
  let hit = full.indexOf(withContext)
  if (hit !== -1) {
    const start = hit + anchor.prefix.length
    return { start, end: start + anchor.exact.length }
  }
  hit = full.indexOf(anchor.exact)
  if (hit !== -1) return { start: hit, end: hit + anchor.exact.length }
  return null
}

/** 遍历容器内文本节点（跳过本功能覆盖层），累计 offset，
 *  把 articleText 下标映射回 DOM Range（供 CSS Custom Highlight API 用）。
 *  下标越界 / 找不到承载节点时返回 null。 */
export function rangeFromHit(
  container: HTMLElement,
  hit: AnchorHit,
): Range | null {
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const el = node.parentElement
      return el?.closest(OVERLAY_SELECTOR) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT
    },
  })
  let offset = 0
  let startNode: Text | null = null
  let startOffset = 0
  let endNode: Text | null = null
  let endOffset = 0
  for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
    const text = node as Text
    const len = text.data.length
    const nodeStart = offset
    const nodeEnd = offset + len
    if (startNode === null && hit.start < nodeEnd) {
      startNode = text
      startOffset = hit.start - nodeStart
    }
    if (hit.end <= nodeEnd && hit.end > nodeStart) {
      endNode = text
      endOffset = hit.end - nodeStart
      break
    }
    offset = nodeEnd
  }
  if (startNode === null || endNode === null) return null
  const range = document.createRange()
  try {
    range.setStart(startNode, startOffset)
    range.setEnd(endNode, endOffset)
  } catch {
    return null
  }
  return range
}

// ---- 存储（localStorage，设备本地） ----

function pickColor(value: unknown): AnnotationColor {
  return ANNOTATION_COLORS.includes(value as AnnotationColor)
    ? (value as AnnotationColor)
    : 'yellow'
}

/** 不可信 JSON → 合法 Annotation[]（逐条校验，非法丢弃）。 */
function normalizeList(raw: unknown): Annotation[] {
  if (!Array.isArray(raw)) return []
  const out: Annotation[] = []
  for (const item of raw) {
    if (typeof item !== 'object' || item === null) continue
    const a = item as Record<string, unknown>
    const anchor = (a.anchor ?? {}) as Record<string, unknown>
    if (typeof a.id !== 'string' || a.id === '') continue
    if (typeof a.entryRef !== 'string' || a.entryRef === '') continue
    if (typeof anchor.exact !== 'string' || anchor.exact === '') continue
    out.push({
      id: a.id,
      entryRef: a.entryRef,
      color: pickColor(a.color),
      note: typeof a.note === 'string' ? a.note : '',
      anchor: {
        prefix: typeof anchor.prefix === 'string' ? anchor.prefix : '',
        exact: anchor.exact,
        suffix: typeof anchor.suffix === 'string' ? anchor.suffix : '',
      },
      createdAt: typeof a.createdAt === 'number' ? a.createdAt : 0,
      contentVersion: typeof a.contentVersion === 'string' ? a.contentVersion : '',
    })
  }
  return out
}

/** 读取全部批注（损坏数据 → 空数组，不抛错）。 */
// ---- 存储层（F051：服务端真源 + localStorage 离线缓存 + 首次导入） ----

export function readAllAnnotations(): Annotation[] {
  try {
    const raw = localStorage.getItem(ANNOTATIONS_STORAGE_KEY)
    if (raw === null) return []
    return normalizeList(JSON.parse(raw))
  } catch {
    return []
  }
}

/** 读取某篇文章的批注（按 createdAt 升序 = 正文出现顺序近似）。 */
export function readAnnotationsForEntry(entryRef: string): Annotation[] {
  return readAllAnnotations()
    .filter((a) => a.entryRef === entryRef)
    .sort((x, y) => x.createdAt - y.createdAt)
}

function writeAll(list: Annotation[]): void {
  try {
    localStorage.setItem(ANNOTATIONS_STORAGE_KEY, JSON.stringify(list))
  } catch {
    // localStorage 不可用（隐私模式等）：本次保存不落盘，会话内仍可用
  }
}

/** 服务端批注（client.ts Annotation）→ 本地缓存形状。 */
function fromServer(item: {
  id: string
  entryRef: string
  anchor: Record<string, unknown>
  excerpt: string
  note: string
  color: string
  createdAt: string
}): Annotation {
  const anchor = item.anchor as Record<string, unknown>
  return {
    id: item.id,
    entryRef: item.entryRef,
    color: (
      ANNOTATION_COLORS as readonly string[]
    ).includes(item.color)
      ? (item.color as AnnotationColor)
      : 'yellow',
    note: item.note ?? '',
    anchor: {
      prefix: typeof anchor.prefix === 'string' ? anchor.prefix : '',
      exact: typeof anchor.exact === 'string' ? anchor.exact : item.excerpt,
      suffix: typeof anchor.suffix === 'string' ? anchor.suffix : '',
    },
    createdAt: Date.parse(item.createdAt) || 0,
    contentVersion:
      typeof anchor.contentVersion === 'string' ? anchor.contentVersion : '',
  }
}

/** 本地批注 → 服务端 POST 负载（excerpt 取 exact，contentVersion 并入 anchor）。 */
function toServerPayload(annotation: Annotation): {
  entryRef: string
  anchor: Record<string, unknown>
  excerpt: string
  note: string
  color: string
} {
  return {
    entryRef: annotation.entryRef,
    anchor: { ...annotation.anchor, contentVersion: annotation.contentVersion },
    excerpt: annotation.anchor.exact,
    note: annotation.note,
    color: annotation.color,
  }
}

let serverSyncStarted = false

/**
 * F051 首次同步：把本地存量 POST 导入（服务端按 anchor hash 查重，
 * 幂等——重复导入返回既有行），随后用服务端列表覆盖本地缓存。
 * 之后所有读写以服务端为准；本函数在 Reader 挂载批注层时调用一次。
 */
export async function syncAnnotationsWithServer(): Promise<void> {
  if (serverSyncStarted) return
  serverSyncStarted = true
  try {
    const [{ listAnnotations, createAnnotation }, local] = await Promise.all([
      import('../api/client'),
      Promise.resolve(readAllAnnotations()),
    ])
    for (const annotation of local) {
      await createAnnotation(toServerPayload(annotation)).catch(() => {})
    }
    const server = await listAnnotations({})
    writeAll(server.items.map(fromServer))
  } catch {
    // 离线/网络失败：保留本地缓存，下次再试（诚实降级为设备本地）。
    serverSyncStarted = false
  }
}

/** 新增 / 更新一条批注：本地缓存立即生效 + 服务端异步写入。 */
export function saveAnnotation(annotation: Annotation): void {
  const rest = readAllAnnotations().filter((a) => a.id !== annotation.id)
  writeAll([...rest, annotation])
  void (async () => {
    try {
      const { createAnnotation } = await import('../api/client')
      const saved = await createAnnotation(toServerPayload(annotation))
      const withServerId = readAllAnnotations().map((a) =>
        a.id === annotation.id ? { ...a, id: saved.id } : a,
      )
      writeAll(withServerId)
    } catch {
      // 离线：本地缓存仍有效，服务端同步待下次 sync 补偿
    }
  })()
}

/** 删除一条批注（本地 + 服务端 fire-and-forget）。 */
export function deleteAnnotation(id: string): void {
  writeAll(readAllAnnotations().filter((a) => a.id !== id))
  void (async () => {
    try {
      const client = await import('../api/client')
      await client.deleteAnnotation(id)
    } catch {
      // 离线：下次 sync 后与服务端收敛
    }
  })()
}
