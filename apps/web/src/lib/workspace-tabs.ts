/** workspace-tabs — N103/N104/N101 工作区标签页设备本地状态。
 *
 * 全部状态只存本机 localStorage（绝不进 BFF、绝不跨设备同步）：
 * - 最近关闭（N104）：LRU 上限 20，按最近关闭排序，ref 去重；
 * - 分组折叠状态（N101）：每工作区一组名集合（折叠 = 隐藏组体）；
 * - 预览笔记草稿（N103）：每 (workspaceId, ref) 一份文本草稿——
 *   「未保存」= 编辑后尚未显式保存/放弃，替换预览会被拦截。
 *
 * 存储不可用（隐私模式/满）→ 优雅降级为内存行为，绝不抛错打断阅读。
 */

export interface RecentClosedItem {
  ref: string
  title: string
  /** 安全外链（仅绝对 http/https；可空 = 无外链）。 */
  url: string | null
  workspaceId: string
  closedAt: string
}

export const RECENTLY_CLOSED_CAP = 20

const RECENTLY_CLOSED_KEY = 'lumi-workspace-recently-closed-v1'
const COLLAPSED_GROUPS_KEY = 'lumi-workspace-groups-collapsed-v1'
const PREVIEW_DRAFTS_KEY = 'lumi-workspace-preview-drafts-v1'

function storage(): Storage | null {
  try {
    if (typeof localStorage === 'undefined') return null
    return localStorage
  } catch {
    return null
  }
}

function readJson<T>(key: string, fallback: T): T {
  const raw = storage()?.getItem(key)
  if (raw === null || raw === undefined) return fallback
  try {
    const parsed = JSON.parse(raw) as T
    return parsed ?? fallback
  } catch {
    return fallback
  }
}

function writeJson(key: string, value: unknown): void {
  try {
    storage()?.setItem(key, JSON.stringify(value))
  } catch {
    // 存储满/不可用：静默降级（设备本地增强，不值得打断用户）。
  }
}

// ---- N104：最近关闭（LRU 20，ref 去重，最近的在前） ------------------------

export function loadRecentlyClosed(): RecentClosedItem[] {
  const items = readJson<RecentClosedItem[]>(RECENTLY_CLOSED_KEY, [])
  if (!Array.isArray(items)) return []
  return items.filter(
    (it): it is RecentClosedItem =>
      it !== null && typeof it === 'object' && typeof it.ref === 'string',
  )
}

export function pushRecentlyClosed(item: Omit<RecentClosedItem, 'closedAt'>): RecentClosedItem[] {
  const rest = loadRecentlyClosed().filter((it) => it.ref !== item.ref)
  const next = [{ ...item, closedAt: new Date().toISOString() }, ...rest]
  const capped = next.slice(0, RECENTLY_CLOSED_CAP)
  writeJson(RECENTLY_CLOSED_KEY, capped)
  return capped
}

export function clearRecentlyClosed(): RecentClosedItem[] {
  writeJson(RECENTLY_CLOSED_KEY, [])
  return []
}

// ---- N101：分组折叠状态（每工作区） ----------------------------------------

function readCollapsedMap(): Record<string, string[]> {
  return readJson<Record<string, string[]>>(COLLAPSED_GROUPS_KEY, {})
}

/** 折叠的组名列表（null = 未分组隐式前置组，用 '\u0000' 键存）。 */
const UNGROUPED_KEY = '\u0000ungrouped'

export function loadCollapsedGroups(workspaceId: string): Set<string> {
  const names = readCollapsedMap()[workspaceId]
  return new Set(Array.isArray(names) ? names : [])
}

export function saveCollapsedGroups(workspaceId: string, collapsed: Iterable<string>): void {
  const map = readCollapsedMap()
  map[workspaceId] = Array.from(collapsed)
  writeJson(COLLAPSED_GROUPS_KEY, map)
}

/** 组名 → 折叠存储键（未分组用保留键，避免与真实组名冲突）。 */
export function collapseKeyFor(groupName: string | null): string {
  return groupName === null ? UNGROUPED_KEY : groupName
}

// ---- N103：预览笔记草稿（本机；未保存 = 脏） --------------------------------

interface DraftRecord {
  text: string
  savedAt: string
}

function draftsMap(): Record<string, DraftRecord> {
  return readJson<Record<string, DraftRecord>>(PREVIEW_DRAFTS_KEY, {})
}

function draftKey(workspaceId: string, ref: string): string {
  return `${workspaceId}::${ref}`
}

/** 已保存的草稿文本（无 = 空串）。 */
export function loadPreviewDraft(workspaceId: string, ref: string): string {
  return draftsMap()[draftKey(workspaceId, ref)]?.text ?? ''
}

/** 保存草稿（显式保存动作；保存后不算「未保存」）。 */
export function savePreviewDraft(workspaceId: string, ref: string, text: string): void {
  const map = draftsMap()
  const clean = text === '' ? null : { text, savedAt: new Date().toISOString() }
  if (clean === null) {
    delete map[draftKey(workspaceId, ref)]
  } else {
    map[draftKey(workspaceId, ref)] = clean
  }
  writeJson(PREVIEW_DRAFTS_KEY, map)
}

/** 放弃草稿（显式放弃动作）。 */
export function discardPreviewDraft(workspaceId: string, ref: string): void {
  savePreviewDraft(workspaceId, ref, '')
}

/** 该预览是否有「未保存」的笔记草稿（当前编辑文本 ≠ 已保存草稿）。 */
export function hasUnsavedDraft(
  workspaceId: string,
  ref: string,
  currentText: string,
): boolean {
  return currentText !== loadPreviewDraft(workspaceId, ref)
}
