/** settings-conflict — F116 设置冲突解决（store + 决策逻辑）。
 *
 * settings-sync 遇到 409 app_settings_conflict 时不再静默 rehydrate：
 * 把 {serverState, localPending} 快照放进本 store 并触发 ConflictDialog。
 * 对话框逐字段列出 本地候选 vs 服务端当前（默认服务端），「提交所选」
 * 组装所选字段 + 新 baseRevision 走 resolveSettingsConflict；
 * 再次冲突 → 快照刷新、对话框保持再选；取消 → 采用服务端（本地未选
 * 字段丢弃——对话框里明确警示）；网络失败 → 对话框保留不丢。 */

import { create } from 'zustand'

import { patchServerSettings } from '../api/client'

export interface SettingsConflictState {
  /** 服务端当前快照（键 → 值；含 revision 供再次提交的 baseRevision）。 */
  serverState: Record<string, unknown> | null
  serverRevision: number | null
  /** 冲突时本地待写的候选值（键 → 值）。 */
  localPending: Record<string, unknown> | null
}

interface SettingsConflictStore {
  conflict: SettingsConflictState | null
  setConflict: (conflict: SettingsConflictState | null) => void
  clearConflict: () => void
}

export const useSettingsConflict = create<SettingsConflictStore>((set) => ({
  conflict: null,
  setConflict: (conflict) => set({ conflict }),
  clearConflict: () => set({ conflict: null }),
}))

/** settings-sync 的 409 路径调用：登记冲突快照（触发对话框）。 */
export function reportSettingsConflict(
  serverState: Record<string, unknown>,
  serverRevision: number | null,
  localPending: Record<string, unknown>,
): void {
  useSettingsConflict.getState().setConflict({
    serverState,
    serverRevision,
    localPending,
  })
}

export type ConflictResolveOutcome =
  | 'resolved'
  | 'conflict-again'
  | 'network-error'

/** 「提交所选」：只把用户勾选的本地候选字段 PATCH 上去（其余采用服务
 * 端当前值），携带对话框刷新时拿到的 baseRevision。再次冲突 → 快照
 * 刷新并返回 conflict-again（对话框保持）；网络失败 → network-error
 * （对话框保留，不静默丢）。 */
export async function resolveSettingsConflict(
  chosenLocalKeys: string[],
): Promise<ConflictResolveOutcome> {
  const store = useSettingsConflict.getState()
  const conflict = store.conflict
  if (conflict === null) return 'resolved'
  const localPending = conflict.localPending ?? {}
  const merged: Record<string, unknown> = { ...(conflict.serverState ?? {}) }
  for (const key of chosenLocalKeys) {
    if (key in localPending) merged[key] = localPending[key]
  }
  const body: Record<string, unknown> = { ...merged }
  if (conflict.serverRevision !== null) body.baseRevision = conflict.serverRevision
  try {
    await patchServerSettings(body as never)
    store.clearConflict()
    return 'resolved'
  } catch (error) {
    const status =
      typeof error === 'object' && error !== null && 'status' in error
        ? (error as { status?: number }).status
        : undefined
    if (status === 409) {
      // 再次冲突：刷新服务端快照，对话框保持（本地候选保留）
      const server = await import('../api/client').then((m) =>
        m.getServerSettings().catch(() => null),
      )
      if (server !== null) {
        reportSettingsConflict(
          server as unknown as Record<string, unknown>,
          typeof server.revision === 'number' ? server.revision : null,
          localPending,
        )
        return 'conflict-again'
      }
      return 'network-error'
    }
    return 'network-error'
  }
}

/** 「取消 / 采用服务端」：丢弃全部本地候选（对话框内已有明确警示）。 */
export function discardSettingsConflict(): void {
  useSettingsConflict.getState().clearConflict()
}
