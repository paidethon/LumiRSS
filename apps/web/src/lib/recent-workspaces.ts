/** recent-workspaces — N110 最近工作区（设备本地，per-user 键命名空间）。
 *
 * 与 recent-reads（F10/N103 语义）同一约定：
 * - localStorage 键 = `lumirss-recent-workspaces:<userId>` —— 键里带
 *   用户 id：同浏览器换账号绝不显示他人记录（不共享、不 shadow-copy
 *   服务端状态）；
 * - 最多 3 条 [{workspaceId, name, openedAt}]，新记录置顶去重；
 * - 记录点：WorkspacesPage 打开/切换工作区（打开即记录，仅本地）；
 * - localStorage 满/不可用：静默不阻塞（历史是增强数据）。
 */

export interface RecentWorkspaceEntry {
  workspaceId: string
  name: string
  openedAt: string
}

export const RECENT_WORKSPACES_LIMIT = 3

function storageKey(userId: string): string {
  return `lumirss-recent-workspaces:${userId}`
}

/** 解析持久化 JSON：逐条校验，非法条目丢弃（corrupted 数据不致崩）。 */
function normalize(raw: unknown): RecentWorkspaceEntry[] {
  if (!Array.isArray(raw)) return []
  const seen = new Set<string>()
  const out: RecentWorkspaceEntry[] = []
  for (const item of raw) {
    if (typeof item !== 'object' || item === null) continue
    const r = item as Record<string, unknown>
    if (typeof r.workspaceId !== 'string' || r.workspaceId === '') continue
    if (typeof r.openedAt !== 'string') continue
    if (seen.has(r.workspaceId)) continue
    seen.add(r.workspaceId)
    out.push({
      workspaceId: r.workspaceId,
      name: typeof r.name === 'string' ? r.name : '',
      openedAt: r.openedAt,
    })
  }
  return out
}

/** 最近工作区列表（新 → 旧，最多 3 条）。userId 为空 / 不可用 → []。 */
export function listRecentWorkspaces(userId: string): RecentWorkspaceEntry[] {
  if (!userId || typeof localStorage === 'undefined') return []
  try {
    const raw = localStorage.getItem(storageKey(userId))
    if (raw === null) return []
    return normalize(JSON.parse(raw)).slice(0, RECENT_WORKSPACES_LIMIT)
  } catch {
    return []
  }
}

/** 记录一次打开：置顶去重（同 id 移到最前并刷新时间），截断上限。
 * userId 为空（未登录态）no-op。 */
export function recordRecentWorkspace(
  userId: string,
  entry: { workspaceId: string; name?: string | null },
  now: Date = new Date(),
): RecentWorkspaceEntry[] {
  if (!userId || typeof localStorage === 'undefined') return listRecentWorkspaces(userId)
  if (!entry.workspaceId) return listRecentWorkspaces(userId)
  const previous = listRecentWorkspaces(userId)
  const rest = previous.filter((it) => it.workspaceId !== entry.workspaceId)
  const next: RecentWorkspaceEntry[] = [
    {
      workspaceId: entry.workspaceId,
      name: entry.name ?? '',
      openedAt: now.toISOString(),
    },
    ...rest,
  ].slice(0, RECENT_WORKSPACES_LIMIT)
  try {
    localStorage.setItem(storageKey(userId), JSON.stringify(next))
  } catch {
    // localStorage 满/不可用：静默不阻塞
  }
  return next
}

/** 清空某用户的最近工作区（返回清空后的列表，恒为 []）。 */
export function clearRecentWorkspaces(userId: string): RecentWorkspaceEntry[] {
  if (!userId || typeof localStorage === 'undefined') return []
  try {
    localStorage.removeItem(storageKey(userId))
  } catch {
    // 静默
  }
  return []
}
