/** F018 相同链接聚合 —— 展示层归一化与折叠（只折叠，不删除、不改已读）。
 *
 * normalizeContentUrl 与 BFF url_normalize 同规则子集（小写 host、去尾
 * 斜杠、忽略 http/https、去已知追踪参数；签名参数保留、路径参与 key）。
 * 折叠范围诚实：仅折叠「当前页内」normalized 相同的链接（面板标注
 * 「仅本页」），跨页绝不误合。 */

export interface AggregatableItem {
  entryRef: string
  url?: string | null
}

export function isTrackingParam(name: string): boolean {
  const lowered = name.toLowerCase()
  if (lowered === 'token' || lowered === 'sig' || lowered.endsWith('_signature')) return false
  return (
    lowered.startsWith('utm_') ||
    ['fbclid', 'gclid', 'msclkid', 'igshid', 'mc_cid', 'mc_eid'].includes(lowered)
  )
}

/** 与 BFF 同规则的归一化；非 http(s) → null（不参与聚合）。 */
export function normalizeContentUrl(url: string): string | null {
  if (typeof url !== 'string' || url.trim() === '') return null
  let parsed: URL
  try {
    parsed = new URL(url.trim())
  } catch {
    return null
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null
  const host = parsed.hostname.toLowerCase()
  let path = parsed.pathname || '/'
  if (path.length > 1 && path.endsWith('/')) path = path.replace(/\/+$/, '')
  const kept: string[] = []
  parsed.searchParams.forEach((value, name) => {
    if (!isTrackingParam(name)) kept.push(`${name}=${value}`)
  })
  const query = kept.join('&')
  return `${host}${path}${query !== '' ? `?${query}` : ''}`
}

export interface UrlGroup<T extends AggregatableItem> {
  /** 组代表（第一条；保留其原始 url 与已读状态）。 */
  primary: T
  /** 其余同链条目（不同来源/时间，展开可见）。 */
  duplicates: T[]
  /** 归一化依据（供「3 个来源收录」说明）。 */
  key: string
}

/**
 * 当前页内聚合：normalized 相同的条目折叠为一组（组代表为首条）。
 * 无 url / 归一化失败的条目原样保留（各自成组，不参与合并）。
 */
export function aggregateByNormalizedUrl<T extends AggregatableItem>(
  items: T[],
): { visible: T[]; groups: Map<string, UrlGroup<T>> } {
  const groups = new Map<string, UrlGroup<T>>()
  const visible: T[] = []
  const claimed = new Set<string>()
  for (const item of items) {
    if (claimed.has(item.entryRef)) continue
    const key = item.url != null ? normalizeContentUrl(item.url) : null
    if (key === null) {
      visible.push(item)
      continue
    }
    const same = items.filter(
      (other) =>
        other.entryRef !== item.entryRef &&
        !claimed.has(other.entryRef) &&
        other.url != null &&
        normalizeContentUrl(other.url) === key,
    )
    if (same.length === 0) {
      visible.push(item)
      continue
    }
    const duplicates = same.slice(0, 4) // 有界展示：组内最多 5 条
    for (const dup of duplicates) claimed.add(dup.entryRef)
    claimed.add(item.entryRef)
    groups.set(item.entryRef, { primary: item, duplicates, key })
    visible.push(item)
  }
  return { visible, groups }
}
