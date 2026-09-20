/** draft-store — F119 本机编辑草稿恢复（受控文本表单白名单注册制）。
 *
 * - 只有显式注册的表单（formId 白名单）会被自动保存；密码/API key
 *   表单绝不注册（负向：注册表外表单零留存）。
 * - debounce 2s 写 localStorage（key `lumirss-draft-<formId>`，每条
 *   ≤50KB，全库 ≤20 条 LRU）；存储满 → 静默跳过 + 一次性提示。
 * - 重新打开同表单且 draft.updated_at 较新 → 恢复条数据（恢复/放弃/
 *   对照三选）；登出清理全部草稿。 */

const PREFIX = 'lumirss-draft-'
const MAX_DRAFTS = 20
const MAX_BYTES = 50 * 1024
const DEBOUNCE_MS = 2000

export interface DraftRecord {
  values: Record<string, string>
  updatedAt: string
}

/** 白名单：允许自动保存的表单 id（密码/密钥表单永不出现在此）。 */
const REGISTRY = new Set<string>([
  'note-editor',
  'annotation-editor',
  'qa-template-dialog',
  'clip-note-dialog',
])

let warnShown = false
let timer: ReturnType<typeof setTimeout> | null = null

function storage(): Storage | null {
  try {
    if (typeof localStorage === 'undefined') return null
    return localStorage
  } catch {
    return null
  }
}

export function isDraftRegistered(formId: string): boolean {
  return REGISTRY.has(formId)
}

/** 测试/文档用途：只读白名单（运行时不可变）。 */
export function registeredDraftForms(): string[] {
  return [...REGISTRY]
}

function readDraft(formId: string): DraftRecord | null {
  const store = storage()
  if (store === null || !REGISTRY.has(formId)) return null
  try {
    const raw = store.getItem(PREFIX + formId)
    if (raw === null) return null
    const parsed = JSON.parse(raw) as DraftRecord
    if (
      typeof parsed !== 'object' ||
      parsed === null ||
      typeof parsed.updatedAt !== 'string' ||
      typeof parsed.values !== 'object'
    ) {
      return null
    }
    return parsed
  } catch {
    return null
  }
}

function listDraftKeys(): string[] {
  const store = storage()
  if (store === null) return []
  const keys: string[] = []
  for (let i = 0; i < store.length; i += 1) {
    const key = store.key(i)
    if (key !== null && key.startsWith(PREFIX)) keys.push(key)
  }
  return keys
}

function writeDraftNow(formId: string, values: Record<string, string>): boolean {
  const store = storage()
  if (store === null || !REGISTRY.has(formId)) return false
  const record: DraftRecord = {
    values,
    updatedAt: new Date().toISOString(),
  }
  const serialized = JSON.stringify(record)
  if (serialized.length > MAX_BYTES) {
    if (!warnShown && typeof console !== 'undefined') {
      warnShown = true
      console.info('草稿过大，已跳过自动保存（不影响表单本身）。')
    }
    return false
  }
  // LRU 上限：满了先删最旧的
  const keys = listDraftKeys()
  if (!keys.includes(PREFIX + formId) && keys.length >= MAX_DRAFTS) {
    const sorted = keys
      .map((key) => {
        try {
          const parsed = JSON.parse(store.getItem(key) ?? '{}') as DraftRecord
          return { key, at: parsed.updatedAt ?? '' }
        } catch {
          return { key, at: '' }
        }
      })
      .sort((a, b) => a.at.localeCompare(b.at))
    const overflow = keys.length - MAX_DRAFTS + 1
    for (const item of sorted.slice(0, overflow)) {
      try {
        store.removeItem(item.key)
      } catch {
        /* ignore */
      }
    }
  }
  try {
    store.setItem(PREFIX + formId, serialized)
    return true
  } catch {
    // 存储满：静默跳过 + 一次性提示
    if (!warnShown && typeof console !== 'undefined') {
      warnShown = true
      console.info('本地存储已满，草稿自动保存暂不可用。')
    }
    return false
  }
}

/** 受控表单变更入口：debounce 2s 后落盘。未注册的 formId 直接忽略。 */
export function saveDraft(formId: string, values: Record<string, string>): void {
  if (!REGISTRY.has(formId)) return
  if (timer !== null) clearTimeout(timer)
  timer = setTimeout(() => {
    timer = null
    writeDraftNow(formId, values)
  }, DEBOUNCE_MS)
}

/** 表单成功提交 → 清除该表单草稿。 */
export function clearDraft(formId: string): void {
  const store = storage()
  if (store === null) return
  if (timer !== null) {
    clearTimeout(timer)
    timer = null
  }
  try {
    store.removeItem(PREFIX + formId)
  } catch {
    /* ignore */
  }
}

/** 恢复决策：草稿存在且比已保存版本新（savedAt 缺省视为旧）。 */
export function loadDraftIfNewer(
  formId: string,
  savedAt: string | null,
): DraftRecord | null {
  const draft = readDraft(formId)
  if (draft === null) return null
  if (savedAt !== null && draft.updatedAt <= savedAt) return null
  return draft
}

/** 对照视图数据：草稿 vs 当前已保存值，逐字段并排。 */
export function diffDraft(
  draft: DraftRecord,
  current: Record<string, string>,
): Array<{ field: string; draftValue: string; currentValue: string }> {
  const fields = new Set([...Object.keys(draft.values), ...Object.keys(current)])
  return [...fields].map((field) => ({
    field,
    draftValue: draft.values[field] ?? '',
    currentValue: current[field] ?? '',
  }))
}

/** 登出清理：删除全部草稿（白名单内所有键）。 */
export function clearAllDrafts(): void {
  const store = storage()
  if (store === null) return
  for (const key of listDraftKeys()) {
    try {
      store.removeItem(key)
    } catch {
      /* ignore */
    }
  }
}

/** 测试专用：立即冲刷 pending 的 debounce 写入。 */
export function flushDraftForTests(formId: string, values: Record<string, string>): void {
  if (timer !== null) {
    clearTimeout(timer)
    timer = null
  }
  writeDraftNow(formId, values)
}
