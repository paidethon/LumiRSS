/** offline-quota — N183：离线资料设备配额（device-local）。
 *
 * 枚举本设备的 Cache Storage（PWA 离线缓存），统计用量；清理预览按
 * 「大 → 小、旧 → 新」排出的条目集合；应用只删除 Cache Storage 里的
 * 缓存条目——绝不调用任何网络 API，服务器上的收藏 / 人工笔记 /
 * 阅读状态完全不受影响（配额也保存在本设备 localStorage）。
 *
 * 环境无 caches（非安全上下文 / 测试）→ usage 返回 available:false，
 * UI 如实显示「本设备不支持离线缓存统计」，绝不冒充 0。
 */

export const OFFLINE_QUOTA_KEY = 'lumirss-offline-quota-mb'
export const OFFLINE_QUOTA_DEFAULT_MB = 200
export const OFFLINE_QUOTA_MIN_MB = 50
export const OFFLINE_QUOTA_MAX_MB = 2048

export interface CacheEntryInfo {
  cacheName: string
  url: string
  sizeBytes: number | null
  /** cachedAt：条目响应的 Date 头（缺失 → null，排序时当作最旧）。 */
  cachedAt: number | null
}

export interface CacheUsage {
  available: boolean
  cacheCount: number
  entryCount: number
  knownBytes: number
  /** sizeBytes 不可读（opaque 响应等）的条目数——如实分开，不冒充 0。 */
  unknownSizeCount: number
  entries: CacheEntryInfo[]
}

export interface CleanupPreviewItem {
  cacheName: string
  url: string
  sizeBytes: number | null
}

export function readQuotaMb(storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage): number {
  if (storage === null) return OFFLINE_QUOTA_DEFAULT_MB
  try {
    const raw = storage.getItem(OFFLINE_QUOTA_KEY)
    if (raw === null) return OFFLINE_QUOTA_DEFAULT_MB
    const parsed = Number.parseInt(raw, 10)
    if (Number.isNaN(parsed)) return OFFLINE_QUOTA_DEFAULT_MB
    return Math.min(OFFLINE_QUOTA_MAX_MB, Math.max(OFFLINE_QUOTA_MIN_MB, parsed))
  } catch {
    return OFFLINE_QUOTA_DEFAULT_MB
  }
}

export function writeQuotaMb(
  value: number,
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): void {
  if (storage === null) return
  try {
    const clamped = Math.min(OFFLINE_QUOTA_MAX_MB, Math.max(OFFLINE_QUOTA_MIN_MB, Math.round(value)))
    storage.setItem(OFFLINE_QUOTA_KEY, String(clamped))
  } catch {
    // 写失败静默：设备本地偏好
  }
}

type CacheLike = {
  keys: () => Promise<Request[]>
  match: (request: Request) => Promise<Response | undefined>
  delete: (request: Request) => Promise<boolean>
}
type CacheStorageLike = {
  keys: () => Promise<string[]>
  open: (name: string) => Promise<CacheLike>
}

function cachesOrUndefined(): CacheStorageLike | undefined {
  const candidate = (globalThis as unknown as { caches?: CacheStorageLike }).caches
  return candidate && typeof candidate.open === 'function' ? candidate : undefined
}

async function entrySize(request: Request, cache: CacheLike): Promise<{ size: number | null; cachedAt: number | null }> {
  try {
    const response = await cache.match(request)
    if (!response) return { size: null, cachedAt: null }
    const dateHeader = response.headers.get('date')
    const cachedAt = dateHeader ? Date.parse(dateHeader) : null
    // content-length 常缺失；用 blob 实测。opaque 响应 blob 为 0 —— 用
    // type 区分：opaque 视为「大小未知」，如实计入 unknownSizeCount。
    if (response.type === 'opaque') return { size: null, cachedAt }
    const blob = await response.blob()
    return { size: blob.size, cachedAt: Number.isNaN(cachedAt ?? NaN) ? null : cachedAt }
  } catch {
    return { size: null, cachedAt: null }
  }
}

/** 枚举当前设备的全部 Cache Storage 条目（只读）。 */
export async function enumerateCacheEntries(): Promise<CacheUsage> {
  const caches = cachesOrUndefined()
  if (!caches) {
    return { available: false, cacheCount: 0, entryCount: 0, knownBytes: 0, unknownSizeCount: 0, entries: [] }
  }
  const names = await caches.keys()
  const entries: CacheEntryInfo[] = []
  for (const name of names) {
    const cache = await caches.open(name)
    const requests = await cache.keys()
    for (const request of requests) {
      const { size, cachedAt } = await entrySize(request, cache)
      entries.push({ cacheName: name, url: request.url, sizeBytes: size, cachedAt })
    }
  }
  const knownBytes = entries.reduce((sum, entry) => sum + (entry.sizeBytes ?? 0), 0)
  return {
    available: true,
    cacheCount: names.length,
    entryCount: entries.length,
    knownBytes,
    unknownSizeCount: entries.filter((entry) => entry.sizeBytes === null).length,
    entries,
  }
}

function entryTime(entry: CacheEntryInfo): number {
  return entry.cachedAt ?? 0
}

/** 清理预览：从超出配额的部分中挑出应删除的条目（大 → 小、旧 → 新）。
 * 无法确定大小的条目排在最后（只在大到不得不删时才考虑）。 */
export function planCleanup(
  usage: CacheUsage,
  quotaBytes: number,
): { overQuota: boolean; candidates: CleanupPreviewItem[]; reclaimableBytes: number } {
  const over = usage.knownBytes - quotaBytes
  if (usage.available && over <= 0) {
    return { overQuota: false, candidates: [], reclaimableBytes: 0 }
  }
  const sized = usage.entries.filter((entry) => entry.sizeBytes !== null)
  const unsized = usage.entries.filter((entry) => entry.sizeBytes === null)
  // 大 → 小；大小相同 → 旧 → 新
  const ordered = [...sized].sort((a, b) => {
    const sizeDelta = (b.sizeBytes ?? 0) - (a.sizeBytes ?? 0)
    if (sizeDelta !== 0) return sizeDelta
    return entryTime(a) - entryTime(b)
  })
  const candidates: CleanupPreviewItem[] = []
  let reclaimed = 0
  for (const entry of ordered) {
    if (!usage.available || reclaimed < over) {
      candidates.push({ cacheName: entry.cacheName, url: entry.url, sizeBytes: entry.sizeBytes })
      reclaimed += entry.sizeBytes ?? 0
    }
  }
  // 仍超配额且只剩未知大小条目 → 它们按旧 → 新补进候选
  if (usage.available && reclaimed < over) {
    const orderedUnsized = [...unsized].sort((a, b) => entryTime(a) - entryTime(b))
    for (const entry of orderedUnsized) {
      candidates.push({ cacheName: entry.cacheName, url: entry.url, sizeBytes: null })
    }
  }
  return { overQuota: true, candidates, reclaimableBytes: reclaimed }
}

/** 应用清理：只删除给定 Cache Storage 条目；绝不发起任何网络请求。
 * 返回实际删除的条目数。 */
export async function applyCleanup(candidates: CleanupPreviewItem[]): Promise<number> {
  const caches = cachesOrUndefined()
  if (!caches) return 0
  const byCache = new Map<string, string[]>()
  for (const candidate of candidates) {
    const urls = byCache.get(candidate.cacheName) ?? []
    urls.push(candidate.url)
    byCache.set(candidate.cacheName, urls)
  }
  let deleted = 0
  for (const [name, urls] of byCache) {
    const cache = await caches.open(name)
    const requests = await cache.keys()
    for (const request of requests) {
      if (urls.includes(request.url)) {
        if (await cache.delete(request)) deleted += 1
      }
    }
  }
  return deleted
}
