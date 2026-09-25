/** session-recap — N080 阅读成果汇总（device-local，会话窗口 30 分钟）。
 *
 * 只统计「实际创建成功」的对象：批注 / 阅读问题（N074）/ 知识卡片
 * （N076）的创建调用成功后各记一条事件（kind + entryRef + ts）；
 * 从不把失败的尝试计入，也不预占。entriesTouched = 窗口内事件的
 * 去重 entryRef 数。
 *
 * 存储：localStorage 单键 `lumirss-session-recap-events`（有界 500，
 * 超界丢最旧）；笔记（可编辑）单独存 `lumirss-session-recap-note`。
 * 隐私口径与 recent-reads 相同：仅本设备的 UI 增强数据，绝不上传。
 */

export type RecapEventKind = 'annotation' | 'question' | 'card'

export interface RecapEvent {
  kind: RecapEventKind
  entryRef: string
  ts: number
}

export interface SessionRecap {
  windowMinutes: number
  newAnnotations: number
  questions: number
  cards: number
  entriesTouched: number
}

const EVENTS_KEY = 'lumirss-session-recap-events'
const NOTE_KEY = 'lumirss-session-recap-note'
const MAX_EVENTS = 500
const NOTE_MAX_CHARS = 2000

function readEvents(): RecapEvent[] {
  if (typeof localStorage === 'undefined') return []
  try {
    const raw = localStorage.getItem(EVENTS_KEY)
    if (raw === null) return []
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return []
    const out: RecapEvent[] = []
    for (const item of parsed) {
      if (typeof item !== 'object' || item === null) continue
      const r = item as Record<string, unknown>
      if (r.kind !== 'annotation' && r.kind !== 'question' && r.kind !== 'card') continue
      if (typeof r.entryRef !== 'string') continue
      if (typeof r.ts !== 'number' || !Number.isFinite(r.ts)) continue
      out.push({ kind: r.kind, entryRef: r.entryRef, ts: r.ts })
    }
    return out.slice(-MAX_EVENTS)
  } catch {
    return []
  }
}

function writeEvents(events: RecapEvent[]): void {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(EVENTS_KEY, JSON.stringify(events.slice(-MAX_EVENTS)))
  } catch {
    // 存储失败静默：增强数据不阻塞主流程
  }
}

/** 记录一次「实际创建成功」的对象（创建失败绝不调用本函数）。 */
export function recordRecapEvent(kind: RecapEventKind, entryRef: string, now: number = Date.now()): void {
  if (typeof localStorage === 'undefined') return
  const events = readEvents()
  events.push({ kind, entryRef, ts: now })
  writeEvents(events)
}

/** 窗口（默认 30 分钟）内的成果汇总。零事件 → 全零（诚实空态）。 */
export function sessionRecap(windowMinutes: number = 30, now: number = Date.now()): SessionRecap {
  const since = now - windowMinutes * 60_000
  const events = readEvents().filter((e) => e.ts > since)
  const count = (kind: RecapEventKind) => events.filter((e) => e.kind === kind).length
  return {
    windowMinutes,
    newAnnotations: count('annotation'),
    questions: count('question'),
    cards: count('card'),
    entriesTouched: new Set(events.map((e) => e.entryRef)).size,
  }
}

/** 笔记（device-local，可编辑；≤2000 字符，超限拒绝——诚实截断口径）。 */
export function loadRecapNote(): string {
  if (typeof localStorage === 'undefined') return ''
  try {
    return localStorage.getItem(NOTE_KEY) ?? ''
  } catch {
    return ''
  }
}

export function saveRecapNote(note: string): boolean {
  if (typeof localStorage === 'undefined') return false
  if (note.length > NOTE_MAX_CHARS) return false
  try {
    localStorage.setItem(NOTE_KEY, note)
    return true
  } catch {
    return false
  }
}

export const RECAP_NOTE_MAX_CHARS = NOTE_MAX_CHARS

/** 测试/换账号清理（事件与笔记一起）。 */
export function clearRecap(): void {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.removeItem(EVENTS_KEY)
    localStorage.removeItem(NOTE_KEY)
  } catch {
    // 静默
  }
}
