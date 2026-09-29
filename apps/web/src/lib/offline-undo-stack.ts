/** offline-undo-stack — NEW-359 离线阅读撤销栈（设备本地，纯逻辑核心）。
 *
 * 对**本设备尚未同步**的个人操作逐项撤销；**已同步**的操作明确标注
 * 不能直接撤销（如需更改请再次操作——服务端已是事实源，盲目「反操作
 * 撤销」会掩盖真实状态）。
 *
 * 语义：
 * - 个人操作（标已读/收藏/稍后读）在本设备提交：
 *   - 成功 → 记录为 `synced`（服务端已确认——不可直接撤销）；
 *   - 设备离线（!navigator.onLine）导致提交失败 → 记录为 `pending`
 *     （未同步意图——可逐项撤销 = 放弃这条本机意图，绝不影响服务器）；
 * - 有界 FIFO（20 条），重复操作刷新（同 kind+entryRef 只留最新）；
 * - 存储 localStorage `lumirss-offline-undo`——设备本地数据，换账号
 *   由 auth-reset 统一清（防串号，与 reading-position 同一纪律）；
 * - 撤销只对 `pending` 生效；对 `synced` 的撤销请求被明确拒绝。
 */

export const OFFLINE_UNDO_STORAGE_KEY = 'lumirss-offline-undo'
export const OFFLINE_UNDO_STACK_LIMIT = 20

export type OfflineUndoKind = 'read' | 'star' | 'readLater'

export type OfflineUndoSyncState = 'pending' | 'synced'

export interface OfflineUndoEntry {
  id: string
  kind: OfflineUndoKind
  entryRef: string
  label: string
  syncState: OfflineUndoSyncState
  createdAt: number
}

export const OFFLINE_UNDO_KIND_LABELS: Record<OfflineUndoKind, string> = {
  read: '标为已读',
  star: '收藏',
  readLater: '加入稍后读',
}

function newEntryId(): string {
  return `ou-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

/** 读取栈（最新在前；损坏 / 非法值逐条校验丢弃）。 */
export function readOfflineUndoStack(
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): OfflineUndoEntry[] {
  if (storage === null) return []
  try {
    const raw = storage.getItem(OFFLINE_UNDO_STORAGE_KEY)
    if (raw === null) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    const out: OfflineUndoEntry[] = []
    for (const item of parsed) {
      if (item === null || typeof item !== 'object') continue
      const record = item as Record<string, unknown>
      if (typeof record.entryRef !== 'string' || record.entryRef === '') continue
      if (typeof record.label !== 'string' || record.label === '') continue
      if (record.kind !== 'read' && record.kind !== 'star' && record.kind !== 'readLater') continue
      if (record.syncState !== 'pending' && record.syncState !== 'synced') continue
      out.push({
        id: typeof record.id === 'string' && record.id !== '' ? record.id : newEntryId(),
        kind: record.kind,
        entryRef: record.entryRef,
        label: record.label,
        syncState: record.syncState,
        createdAt: typeof record.createdAt === 'number' ? record.createdAt : 0,
      })
      if (out.length >= OFFLINE_UNDO_STACK_LIMIT) break
    }
    return out
  } catch {
    return []
  }
}

function writeStack(entries: OfflineUndoEntry[], storage: Storage | null): void {
  if (storage === null) return
  try {
    storage.setItem(OFFLINE_UNDO_STORAGE_KEY, JSON.stringify(entries.slice(0, OFFLINE_UNDO_STACK_LIMIT)))
  } catch {
    // 配额 / 隐私模式：本机撤销栈尽力而为。
  }
}

/** 记录一次个人操作（最新在前；同 kind+entryRef 去重只留最新；
 * 超限逐出最旧）。 */
export function recordOfflineUndo(
  input: { kind: OfflineUndoKind; entryRef: string; syncState: OfflineUndoSyncState },
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): OfflineUndoEntry {
  const label = OFFLINE_UNDO_KIND_LABELS[input.kind]
  const entry: OfflineUndoEntry = {
    id: newEntryId(),
    kind: input.kind,
    entryRef: input.entryRef,
    label,
    syncState: input.syncState,
    createdAt: Date.now(),
  }
  const rest = readOfflineUndoStack(storage).filter(
    (item) => !(item.kind === input.kind && item.entryRef === input.entryRef),
  )
  writeStack([entry, ...rest], storage)
  return entry
}

/** 撤销判定（纯）：pending 可撤销；synced 明确拒绝。 */
export function canUndoOfflineEntry(entry: OfflineUndoEntry): boolean {
  return entry.syncState === 'pending'
}

/** 逐项撤销（仅 pending；synced → 拒绝并返回 null，调用方如实提示）。 */
export function undoOfflineEntry(
  id: string,
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): OfflineUndoEntry | null {
  const stack = readOfflineUndoStack(storage)
  const target = stack.find((item) => item.id === id)
  if (target === undefined || !canUndoOfflineEntry(target)) return null
  writeStack(
    stack.filter((item) => item.id !== id),
    storage,
  )
  return target
}

/** 清空（换账号防串号由 auth-reset 调用；面板也提供显式清空）。 */
export function clearOfflineUndoStack(
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): void {
  if (storage === null) return
  try {
    storage.removeItem(OFFLINE_UNDO_STORAGE_KEY)
  } catch {
    // ignore
  }
}

/** 提交失败时是否应记为「未同步」（离线导致的网络失败才入栈；
 * 其余失败按既有批量失败清单处理，不入撤销栈）。 */
export function shouldRecordAsPending(online: boolean): boolean {
  return !online
}
