/** recent-reads — F10 最近阅读（本地历史，设备本地 UI 数据）。
 *
 * localStorage 单 key（`lumirss-recent-reads`）：
 * - 最多 30 条 [{entryRef, feedTitle, title, openedAt}]，新记录置顶去重；
 * - 记录点：EntryCard / EntryRow 的行点击（打开文章即记录，selectEntry
 *   本就不标已读，这里也不标——只是「打开过」的痕迹）；
 * - 开关存 `lumirss-recent-reads-enabled`（默认 '1'）；关闭后
 *   recordRecentRead 直接 no-op；
 * - localStorage 满/不可用（QuotaExceededError、隐私模式）：静默不阻塞
 *   ——历史是增强数据，绝不能影响打开文章的主流程。
 *
 * 与 reading-position（阅读进度）无关：这里只存「打开过什么」的列表
 * 元信息，不存滚动位置，不 shadow-copy 任何服务端状态。 */

const STORAGE_KEY = 'lumirss-recent-reads'
const ENABLED_KEY = 'lumirss-recent-reads-enabled'
const MAX_ITEMS = 30

export const RECENT_READS_LIMIT = MAX_ITEMS

export interface RecentReadEntry {
  entryRef: string
  feedTitle: string
  title: string
  /** ISO 时间戳（打开时间） */
  openedAt: string
}

function readEnabled(): boolean {
  try {
    return localStorage.getItem(ENABLED_KEY) !== '0'
  } catch {
    return true
  }
}

/** 开关（默认开）；关闭后 recordRecentRead no-op，面板里也可切换。 */
export function isRecentReadsEnabled(): boolean {
  if (typeof localStorage === 'undefined') return true
  return readEnabled()
}

export function setRecentReadsEnabled(enabled: boolean): void {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(ENABLED_KEY, enabled ? '1' : '0')
  } catch {
    /* 写失败静默：开关只影响后续记录 */
  }
}

/** 解析持久化 JSON：逐条校验，非法条目丢弃（corrupted 数据不致崩）。 */
function normalize(raw: unknown): RecentReadEntry[] {
  if (!Array.isArray(raw)) return []
  const seen = new Set<string>()
  const out: RecentReadEntry[] = []
  for (const item of raw) {
    if (typeof item !== 'object' || item === null) continue
    const r = item as Record<string, unknown>
    if (typeof r.entryRef !== 'string' || r.entryRef === '') continue
    if (typeof r.title !== 'string') continue
    if (typeof r.openedAt !== 'string') continue
    if (seen.has(r.entryRef)) continue
    seen.add(r.entryRef)
    out.push({
      entryRef: r.entryRef,
      title: r.title,
      feedTitle: typeof r.feedTitle === 'string' ? r.feedTitle : '',
      openedAt: r.openedAt,
    })
  }
  return out
}

function write(items: RecentReadEntry[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, MAX_ITEMS)))
  } catch {
    // localStorage 满/不可用：静默不阻塞（记录失败不影响打开文章）
  }
}

/** 记录一次打开：置顶去重（同 entryRef 移到最前并刷新时间），截断上限。
 * 开关关闭或参数无效时 no-op。 */
export function recordRecentRead(
  entry: { entryRef: string; feedTitle?: string | null; title?: string | null },
  now: Date = new Date(),
): void {
  if (typeof localStorage === 'undefined') return
  if (!readEnabled()) return
  const entryRef = entry.entryRef
  if (!entryRef) return
  const previous = listRecentReads()
  const rest = previous.filter((it) => it.entryRef !== entryRef)
  const next: RecentReadEntry[] = [
    {
      entryRef,
      feedTitle: entry.feedTitle ?? '',
      title: entry.title ?? '',
      openedAt: now.toISOString(),
    },
    ...rest,
  ].slice(0, MAX_ITEMS)
  write(next)
}

/** 最近阅读列表（新 → 旧；最多 30 条）。不可用/为空返回 []。 */
export function listRecentReads(): RecentReadEntry[] {
  if (typeof localStorage === 'undefined') return []
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw === null) return []
    return normalize(JSON.parse(raw)).slice(0, MAX_ITEMS)
  } catch {
    return []
  }
}

/** 单条移除。 */
export function removeRecentRead(entryRef: string): RecentReadEntry[] {
  const next = listRecentReads().filter((it) => it.entryRef !== entryRef)
  write(next)
  return next
}

/** 清空全部。 */
export function clearRecentReads(): RecentReadEntry[] {
  write([])
  return []
}
