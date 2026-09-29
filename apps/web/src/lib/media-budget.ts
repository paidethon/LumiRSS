/** media-budget — NEW-355 单篇媒体流量预算（设备本地，纯逻辑核心）。
 *
 * 打开大图或音频前显示**已知体积**与加载策略，用户选择只读文字或按次
 * 加载。原则：
 * - 「已知体积」只来自本机已有记录（附件下载队列对同一 URL 记录过的
 *   size）——**绝不发起任何网络请求去测量体积**（零预取）；
 * - 首开媒体体积未知 → 如实标注「未知」，不计入合计；
 * - 策略按**单篇文章**记忆（localStorage `lumirss-media-budget`），
 *   与既有的按源策略（media-policy）和全局图片模式正交；'ask' =
 *   未做单篇决定，跟随全局（不写存储，保持映射紧凑）；
 * - 'text-only' / 'per-load' 的客户端保证复用既有 deferImages 管线
 *   （HTML 进 DOM 前摘除 src/srcset——零媒体请求）。
 */

import { readAttachmentQueue } from './attachment-queue'

export const MEDIA_BUDGET_STORAGE_KEY = 'lumirss-media-budget'

export type MediaBudgetMode = 'ask' | 'text-only' | 'per-load'

export const MEDIA_BUDGET_MODES: readonly MediaBudgetMode[] = ['ask', 'text-only', 'per-load']

export const MEDIA_BUDGET_MODE_LABELS: Record<MediaBudgetMode, string> = {
  ask: '正常加载（跟随全局设置）',
  'text-only': '只读文字（图片与音频保持占位）',
  'per-load': '按次加载（每个媒体显式点击才加载）',
}

export interface MediaBudgetDecision {
  mode: MediaBudgetMode
  decidedAt: string
}

/** 读取单篇决策（损坏 / 非法值 → 'ask'，诚实回退）。 */
export function readMediaBudgetDecision(
  entryRef: string,
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): MediaBudgetDecision | null {
  if (storage === null || entryRef === '') return null
  try {
    const raw = storage.getItem(MEDIA_BUDGET_STORAGE_KEY)
    if (raw === null) return null
    const parsed: unknown = JSON.parse(raw)
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) return null
    const decision = (parsed as Record<string, unknown>)[entryRef] as unknown
    if (decision === null || typeof decision !== 'object') return null
    const record = decision as Record<string, unknown>
    if (!MEDIA_BUDGET_MODES.includes(record.mode as MediaBudgetMode)) return null
    return {
      mode: record.mode as MediaBudgetMode,
      decidedAt: typeof record.decidedAt === 'string' ? record.decidedAt : '',
    }
  } catch {
    return null
  }
}

/** 写入单篇决策（mode = 'ask' 时移除该键；写失败静默：设备本地偏好）。 */
export function writeMediaBudgetDecision(
  entryRef: string,
  mode: MediaBudgetMode,
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): void {
  if (storage === null || entryRef === '') return
  try {
    const raw = storage.getItem(MEDIA_BUDGET_STORAGE_KEY)
    const map =
      raw !== null
        ? (JSON.parse(raw) as Record<string, unknown>)
        : {}
    if (typeof map !== 'object' || map === null || Array.isArray(map)) return
    if (mode === 'ask') delete map[entryRef]
    else map[entryRef] = { mode, decidedAt: new Date().toISOString() }
    storage.setItem(MEDIA_BUDGET_STORAGE_KEY, JSON.stringify(map))
  } catch {
    // 配额满 / 隐私模式：单篇预算是尽力而为的增强。
  }
}

export interface MediaBudgetItem {
  kind: 'image' | 'enclosure'
  /** 图片为占位描述；附件为文件名或 URL 尾段。 */
  label: string
  /** 本机已知的字节数；未知 = null（诚实标注）。 */
  knownBytes: number | null
}

export interface MediaBudgetEstimate {
  items: MediaBudgetItem[]
  /** 仅含已知项的合计（未知项不计入、不假装精确）。 */
  knownTotalBytes: number
  unknownCount: number
  imageCount: number
  enclosureCount: number
}

/** 从本机附件队列找同一 URL 的已知体积（唯一合法的「已知」来源）。 */
export function knownBytesForUrl(
  url: string,
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): number | null {
  const queue = readAttachmentQueue(storage)
  const match = queue.find((item) => item.url === url)
  if (match === undefined) return null
  // 已完成且记录过大小 → 已知；进行中/失败 → 诚实视为未知
  if (match.status === 'done' && typeof match.size === 'number' && match.size >= 0) {
    return match.size
  }
  return null
}

/** 汇总单篇媒体预算：图片计数（体积未知）+ 附件（队列已知体积）。
 * 纯展示数据装配——本函数零网络。 */
export function estimateMediaBudget(input: {
  imageSrcs: string[]
  enclosures: Array<{ href: string; type?: string | null }>
  storage?: Storage | null
}): MediaBudgetEstimate {
  const storage = input.storage ?? (typeof localStorage === 'undefined' ? null : localStorage)
  const items: MediaBudgetItem[] = []
  for (const src of input.imageSrcs) {
    items.push({ kind: 'image', label: `图片（${truncateUrl(src)}）`, knownBytes: null })
  }
  for (const enclosure of input.enclosures) {
    items.push({
      kind: 'enclosure',
      label: `${mediaKindLabel(enclosure.type)}（${truncateUrl(enclosure.href)}）`,
      knownBytes: knownBytesForUrl(enclosure.href, storage),
    })
  }
  let knownTotalBytes = 0
  let unknownCount = 0
  for (const item of items) {
    if (item.knownBytes === null) unknownCount += 1
    else knownTotalBytes += item.knownBytes
  }
  return {
    items,
    knownTotalBytes,
    unknownCount,
    imageCount: input.imageSrcs.length,
    enclosureCount: input.enclosures.length,
  }
}

/** 策略是否要求本文进入「媒体延后」管线（deferImages 同族保证）。 */
export function budgetRequiresDefer(mode: MediaBudgetMode): boolean {
  return mode === 'text-only' || mode === 'per-load'
}

function truncateUrl(url: string): string {
  const path = url.split(/[?#]/)[0] ?? url
  const base = path.split(/[/\\]/).pop() ?? path
  return base.length > 40 ? `${base.slice(0, 37)}…` : base
}

function mediaKindLabel(type: string | null | undefined): string {
  const value = (type ?? '').toLowerCase()
  if (value.startsWith('audio/')) return '音频'
  if (value.startsWith('video/')) return '视频'
  if (value === 'application/pdf' || value === 'application/epub+zip') return '文档'
  if (value.startsWith('image/')) return '图片附件'
  return '媒体附件'
}
