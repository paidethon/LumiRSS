/** N050 个人阅读路径记录 —— 纯设备本地（localStorage），绝不离开本机。
 *
 * - 会话定义：30 分钟无活动窗口——新记录距上一条超过 30 分钟即开启
 *   新会话（旧序列保留在列表前端，最多保留 50 条）；
 * - 记录内容只有 条目引用 + 可选标题 + 时间戳（本机已打开过的文章
 *   顺序），不含正文/进度/任何识别材料；
 * - 「设备本地」是硬边界：本模块没有任何网络调用——API 层（client.ts）
 *   不 import 本模块，服务端也没有任何承载它的端点（负向契约，由
 *   测试断言）；
 * - 可用 disable() 整体停用（停用后 record 即为 no-op），clear() 清空。
 */

const STORAGE_KEY = 'lumi-reading-path'

/** 会话窗口：30 分钟（规格固定；无配置面）。 */
export const READING_PATH_SESSION_WINDOW_MS = 30 * 60 * 1000

/** 列表上限（有界存储；超出裁最旧）。 */
export const READING_PATH_MAX_ENTRIES = 50

export interface ReadingPathEntry {
  /** 统一 ItemRef（rss:<entryRef> / library:<uuid>）。 */
  ref: string
  title: string | null
  /** 记录时刻（本机 ISO 串；仅本机呈现用）。 */
  at: string
}

export interface ReadingPathState {
  enabled: boolean
  entries: ReadingPathEntry[]
}

function defaultState(): ReadingPathState {
  return { enabled: true, entries: [] }
}

function parse(raw: string | null): ReadingPathState {
  if (raw === null) return defaultState()
  try {
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null) return defaultState()
    const obj = parsed as { enabled?: unknown; entries?: unknown }
    const entries = Array.isArray(obj.entries)
      ? obj.entries.filter(
          (entry): entry is ReadingPathEntry =>
            typeof entry === 'object' &&
            entry !== null &&
            typeof (entry as ReadingPathEntry).ref === 'string' &&
            typeof (entry as ReadingPathEntry).at === 'string',
        )
      : []
    return { enabled: obj.enabled !== false, entries }
  } catch {
    return defaultState()
  }
}

function load(): ReadingPathState {
  if (typeof window === 'undefined' || window.localStorage === undefined) {
    return defaultState()
  }
  return parse(window.localStorage.getItem(STORAGE_KEY))
}

function save(state: ReadingPathState): void {
  if (typeof window === 'undefined' || window.localStorage === undefined) return
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
}

/** 记录一次打开。disabled 时为 no-op；距上一条超过会话窗口 → 新会话
 * （旧序列原样保留，新序列垫后）；列表恒 ≤50 条。返回是否记录。 */
export function recordReadingPathEntry(
  ref: string,
  title: string | null = null,
  now: number = Date.now(),
): boolean {
  const state = load()
  if (!state.enabled) return false
  const last = state.entries[state.entries.length - 1]
  const startsNewSession =
    last !== undefined && now - Date.parse(last.at) > READING_PATH_SESSION_WINDOW_MS
  const entry: ReadingPathEntry = {
    ref,
    title,
    at: new Date(now).toISOString(),
  }
  // 同一条目连续重复打开不重复记（避免行内噪声；跨会话的重复仍记）。
  if (last !== undefined && !startsNewSession && last.ref === ref) {
    return false
  }
  let next = state.entries
  if (startsNewSession) {
    next = [...state.entries, entry]
  } else {
    next = [...state.entries, entry]
  }
  save({ enabled: state.enabled, entries: next.slice(-READING_PATH_MAX_ENTRIES) })
  return true
}

export function getReadingPath(): ReadingPathState {
  return load()
}

export function clearReadingPath(): void {
  save({ enabled: load().enabled, entries: [] })
}

export function setReadingPathEnabled(enabled: boolean): void {
  save({ ...load(), enabled })
}

export function isReadingPathEnabled(): boolean {
  return load().enabled
}
