/** search-history — 搜索历史（0011 Gate 4）。
 *
 * 本地 UI 数据（localStorage，`lumirss-search-history` 单 key）：
 * - 上限 10 条，新搜索置顶去重；
 * - 纯函数（push/remove/clear）可单测；
 * - 与生产 API 类型零关系（搜索契约缺口归 0011a）。 */

const STORAGE_KEY = 'lumirss-search-history'
const MAX_HISTORY = 10

export function readSearchHistory(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw === null) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((q): q is string => typeof q === 'string').slice(0, MAX_HISTORY)
  } catch {
    return []
  }
}

function write(items: string[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, MAX_HISTORY)))
  } catch {
    // localStorage 不可用（隐私模式等）：历史降级为会话内不可用，不报错
  }
}

/** 新搜索置顶去重（移除同词条目后 unshift，截断上限） */
export function pushSearchHistory(items: string[], query: string): string[] {
  const q = query.trim()
  if (!q) return items
  const next = [q, ...items.filter((it) => it !== q)].slice(0, MAX_HISTORY)
  write(next)
  return next
}

/** 单条删除 */
export function removeFromSearchHistory(items: string[], query: string): string[] {
  const next = items.filter((it) => it !== query)
  write(next)
  return next
}

/** 清空全部 */
export function clearSearchHistory(items: string[]): string[] {
  void items
  write([])
  return []
}

export const SEARCH_HISTORY_LIMIT = MAX_HISTORY

// ---- F079 搜索历史增强：条目结构 {q, filters?} + 暂停 + 登出清理 ----

export interface SearchHistoryFilters {
  /** 完整高级条件 JSON（与保存视图 filters 同构；可含 feedRef 等）。 */
  [key: string]: unknown
}

export interface SearchHistoryEntry {
  q: string
  filters?: SearchHistoryFilters | null
}

const PAUSED_KEY = 'lumirss-search-history-paused'

function normalize(raw: unknown): SearchHistoryEntry[] {
  if (!Array.isArray(raw)) return []
  const entries: SearchHistoryEntry[] = []
  for (const item of raw.slice(0, MAX_HISTORY)) {
    if (typeof item === 'string') {
      entries.push({ q: item, filters: null }) // 旧结构（纯字符串）兼容
      continue
    }
    if (typeof item === 'object' && item !== null) {
      const q = (item as { q?: unknown }).q
      if (typeof q === 'string' && q.trim() !== '') {
        const filters = (item as { filters?: unknown }).filters
        entries.push({
          q,
          filters:
            filters && typeof filters === 'object'
              ? (filters as SearchHistoryFilters)
              : null,
        })
      }
    }
  }
  return entries
}

/** 读取条目化历史（兼容旧字符串结构；坏 JSON → 空）。 */
export function readSearchHistoryEntries(): SearchHistoryEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw === null) return []
    return normalize(JSON.parse(raw))
  } catch {
    return []
  }
}

function writeEntries(entries: SearchHistoryEntry[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, MAX_HISTORY)))
  } catch {
    /* 忽略 */
  }
}

/** 暂停记录开关（持久化）：暂停后 push 不落盘。 */
export function isHistoryPaused(): boolean {
  try {
    return localStorage.getItem(PAUSED_KEY) === 'true'
  } catch {
    return false
  }
}

export function setHistoryPaused(paused: boolean): void {
  try {
    localStorage.setItem(PAUSED_KEY, paused ? 'true' : 'false')
  } catch {
    /* 忽略 */
  }
}

/** 新增条目（置顶去重 + 上限）；暂停中 → 原样返回不落盘。 */
export function pushSearchHistoryEntry(
  items: SearchHistoryEntry[],
  entry: SearchHistoryEntry,
): SearchHistoryEntry[] {
  const q = entry.q.trim()
  if (!q) return items
  if (isHistoryPaused()) return items
  const next = [
    { ...entry, q },
    ...items.filter((it) => it.q !== q),
  ].slice(0, MAX_HISTORY)
  writeEntries(next)
  return next
}

/** 登出清理：清历史 + 清暂停标记（幂等）。 */
export function clearSearchHistoryOnLogout(): void {
  try {
    localStorage.removeItem(STORAGE_KEY)
    localStorage.removeItem(PAUSED_KEY)
  } catch {
    /* 忽略 */
  }
}

/** 恢复失效条件剥离：filters.feedRef 不在有效来源集合 → 剥离 filters
 * 并提示。返回 (entry, dropped)。 */
export function stripInvalidFilters(
  entry: SearchHistoryEntry,
  validFeedUrls: Set<string>,
): { entry: SearchHistoryEntry; dropped: boolean } {
  const feedRef = entry.filters?.feedRef
  if (entry.filters === null || entry.filters === undefined || feedRef === undefined || feedRef === null) {
    return { entry, dropped: false }
  }
  if (typeof feedRef === 'string' && validFeedUrls.has(feedRef)) {
    return { entry, dropped: false }
  }
  return { entry: { q: entry.q, filters: null }, dropped: true }
}
