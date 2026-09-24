/** goal-conditions — N111 完成条件勾选状态（设备本机）。
 *
 * 服务端只存条件文本本身（workspace_goals.conditions_json）；勾选状态
 * 是纯呈现态：只存本机 localStorage（键 = workspaceId + 条件文本哈希），
 * 绝不进 BFF、绝不跨设备同步。按工作区隔离；清空入口随目标删除/换
 * 条目自动失效（文本不匹配的勾选一律忽略）。
 *
 * 存储不可用（隐私模式/满）→ 优雅降级为内存行为，绝不抛错。
 */

const CHECKED_KEY = 'lumi-goal-conditions-checked-v1'

function storage(): Storage | null {
  try {
    if (typeof localStorage === 'undefined') return null
    return localStorage
  } catch {
    return null
  }
}

function readAll(): Record<string, string[]> {
  const raw = storage()?.getItem(CHECKED_KEY)
  if (raw === null || raw === undefined) return {}
  try {
    const parsed = JSON.parse(raw) as unknown
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return {}
    }
    const result: Record<string, string[]> = {}
    for (const [workspaceId, values] of Object.entries(parsed as Record<string, unknown>)) {
      if (Array.isArray(values)) {
        result[workspaceId] = values.filter((v): v is string => typeof v === 'string')
      }
    }
    return result
  } catch {
    return {}
  }
}

function writeAll(all: Record<string, string[]>): void {
  try {
    storage()?.setItem(CHECKED_KEY, JSON.stringify(all))
  } catch {
    // 存储不可用：静默降级（勾选只活在本渲染周期）。
  }
}

/** 读取某工作区已勾选的条件文本集合（只保留仍存在于清单里的文本）。 */
export function loadCheckedConditions(workspaceId: string, conditions: string[]): Set<string> {
  const stored = readAll()[workspaceId]
  const valid = new Set(conditions)
  return new Set((stored ?? []).filter((text) => valid.has(text)))
}

/** 保存某工作区的勾选集合（只存仍在清单里的文本）。 */
export function saveCheckedConditions(
  workspaceId: string,
  conditions: string[],
  checked: Set<string>,
): void {
  const valid = new Set(conditions)
  const all = readAll()
  all[workspaceId] = [...checked].filter((text) => valid.has(text))
  writeAll(all)
}
