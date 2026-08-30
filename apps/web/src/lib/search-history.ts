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
