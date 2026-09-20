/** custom-shortcuts — F037 快捷键自定义（纯逻辑核心）。
 *
 * - app-settings（device-local）新增 customShortcuts: Record<actionId, combo>；
 * - 解析顺序：用户覆盖 → 默认（effectiveBinding）；
 * - 组合格式：'mod+shift+k' 归一化 token（mod=Ctrl/⌘；arrow 键、单键）；
 * - 保留键黑名单（浏览器必备）拒绝：Ctrl+T/N/W/Tab/L/D、Ctrl+Shift+T/N/Q；
 * - 冲突检测：combo 已被其他 action 占用 → 冲突（覆盖需显式确认）；
 * - 输入框聚焦时不触发（既有守卫保持，在本文件之外）。
 */

export type ShortcutActionId = string

/** 归一化 combo（'Ctrl+Shift+K' → 'mod+shift+k'；'ArrowDown' → 'down'）。 */
export function normalizeCombo(raw: string): string | null {
  if (typeof raw !== 'string') return null
  const ARROWS: Record<string, string> = {
    arrowup: 'up',
    arrowdown: 'down',
    arrowleft: 'left',
    arrowright: 'right',
  }
  const parts = raw
    .split(/[+＋]/)
    .map((part) => part.trim().toLowerCase())
    .filter((part) => part !== '')
    .map((part) => {
      if (part === 'control' || part === 'ctrl' || part === 'cmd' || part === 'meta' || part === '⌘') return 'mod'
      return ARROWS[part] ?? part
    })
  if (parts.length === 0) return null
  const mods: string[] = []
  for (const part of parts) {
    if (part === 'mod' || part === 'alt' || part === 'shift') mods.push(part)
  }
  const keys = parts.filter((p) => !mods.includes(p))
  if (keys.length !== 1 || keys[0] === undefined) return null
  const uniqMods = [...new Set(mods)]
  return [...uniqMods, keys[0]].join('+')
}

/** 展示格式（'mod+shift+k' → 'Ctrl/⌘+Shift+K'；'down' → '↓'）。 */
export function formatCombo(combo: string): string {
  const ARROW_LABELS: Record<string, string> = { up: '↑', down: '↓', left: '←', right: '→' }
  return combo
    .split('+')
    .map((part) => {
      if (part === 'mod') return 'Ctrl/⌘'
      if (part === 'shift') return 'Shift'
      if (part === 'alt') return 'Alt'
      return ARROW_LABELS[part] ?? part.toUpperCase()
    })
    .join('+')
}

/** 浏览器必备组合（黑名单）：分配时直接拒绝。 */
const RESERVED_COMBOS = new Set([
  'mod+t',
  'mod+n',
  'mod+w',
  'mod+tab',
  'mod+l',
  'mod+d',
  'mod+shift+t',
  'mod+shift+n',
  'mod+shift+q',
  'mod+q',
])

export function isReservedCombo(combo: string): boolean {
  const normalized = normalizeCombo(combo)
  return normalized !== null && RESERVED_COMBOS.has(normalized)
}

export interface ConflictResult {
  conflictWith: ShortcutActionId | null
}

/** 冲突检测：combo 已被其他 action 占用 → 返回占用方（覆盖需显式确认）。 */
export function detectConflict(
  custom: Record<ShortcutActionId, string>,
  actionId: ShortcutActionId,
  combo: string,
): ConflictResult {
  const normalized = normalizeCombo(combo)
  if (normalized === null) return { conflictWith: null }
  const owner = Object.entries(custom).find(
    ([id, existing]) => id !== actionId && normalizeCombo(existing) === normalized,
  )
  return { conflictWith: owner?.[0] ?? null }
}

/** 分配入口：黑名单拒绝 / 冲突需显式 overwrite 确认。 */
export function assignShortcut(
  custom: Record<ShortcutActionId, string>,
  actionId: ShortcutActionId,
  combo: string,
  options: { overwrite?: boolean } = {},
): { custom: Record<ShortcutActionId, string>; error: 'reserved' | 'conflict' | null; conflictWith: string | null } {
  if (isReservedCombo(combo)) {
    return { custom, error: 'reserved', conflictWith: null }
  }
  const { conflictWith } = detectConflict(custom, actionId, combo)
  if (conflictWith !== null && options.overwrite !== true) {
    return { custom, error: 'conflict', conflictWith }
  }
  const normalized = normalizeCombo(combo)
  if (normalized === null) return { custom, error: 'conflict', conflictWith: null }
  return {
    custom: { ...custom, [actionId]: normalized },
    error: null,
    conflictWith: null,
  }
}

/** 生效绑定：用户覆盖 → 默认。 */
export function effectiveBinding(
  actionId: ShortcutActionId,
  defaults: Record<ShortcutActionId, string>,
  custom: Record<ShortcutActionId, string>,
): string {
  return custom[actionId] ?? defaults[actionId] ?? ''
}

/** 恢复默认（单项 / 全部）。 */
export function resetShortcut(
  custom: Record<ShortcutActionId, string>,
  actionId?: ShortcutActionId,
): Record<ShortcutActionId, string> {
  if (actionId === undefined) return {}
  const next = { ...custom }
  delete next[actionId]
  return next
}

/** localStorage 持久化（device-local 设置的存取约定）。 */
const STORAGE_KEY = 'lumi.customShortcuts'

export function loadCustomShortcuts(): Record<ShortcutActionId, string> {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (raw === null) return {}
    const parsed = JSON.parse(raw) as Record<string, unknown>
    const out: Record<ShortcutActionId, string> = {}
    for (const [id, combo] of Object.entries(parsed)) {
      if (typeof combo === 'string') {
        const normalized = normalizeCombo(combo)
        if (normalized !== null) out[id] = normalized
      }
    }
    return out
  } catch {
    return {}
  }
}

export function saveCustomShortcuts(custom: Record<ShortcutActionId, string>): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(custom))
  } catch {
    // device-local 存储失败静默（隐私模式等）；本次会话内仍生效。
  }
}
