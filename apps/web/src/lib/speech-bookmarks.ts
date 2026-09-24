/** speech-bookmarks — NF1 N092 听读分段书签（设备本地）。
 *
 * 记录「读到哪一段」：{entryRef, blockIndex, savedAt}，localStorage 单
 * key（lumi-speech-bookmarks），同一 entry 只保留最新一条，容量 LRU 20
 * （最久未写的条目先淘汰）。blockIndex 是朗读块 id
 * （SPEECH_BLOCK_SELECTOR 文档序下标，与高亮/队列共享——见
 * reader-speech.ts），恢复时从该块开头重读：浏览器语音无法在句中定位，
 * 这是诚实语义（chip 有说明文案），不做任何假装精确的进度恢复。
 *
 * 纯设备本地：不进 PORTABLE_KEYS、不参与服务端同步。 */

export const SPEECH_BOOKMARKS_STORAGE_KEY = 'lumi-speech-bookmarks'

/** 容量上限：最旧（最久未更新）的书签先淘汰。 */
export const SPEECH_BOOKMARKS_CAP = 20

export interface SpeechBookmark {
  entryRef: string
  /** 朗读块 id（块序下标）。 */
  blockIndex: number
  /** 保存时刻（epoch ms）。 */
  savedAt: number
}

function readRaw(storage: Storage | null): unknown {
  if (storage === null) return null
  try {
    const raw = storage.getItem(SPEECH_BOOKMARKS_STORAGE_KEY)
    return raw === null ? null : JSON.parse(raw)
  } catch {
    return null
  }
}

/** 归一化：逐条校验（entryRef 非空、blockIndex 非负整数）、按 entryRef
 * 去重（保留靠前者——写入侧已保证最新在前）。损坏数据丢弃而非崩掉。 */
export function normalizeSpeechBookmarks(raw: unknown): SpeechBookmark[] {
  if (!Array.isArray(raw)) return []
  const seen = new Set<string>()
  const out: SpeechBookmark[] = []
  for (const item of raw) {
    if (typeof item !== 'object' || item === null) continue
    const b = item as Record<string, unknown>
    const entryRef = typeof b.entryRef === 'string' ? b.entryRef : ''
    const blockIndex = b.blockIndex
    if (
      entryRef === '' ||
      typeof blockIndex !== 'number' ||
      !Number.isInteger(blockIndex) ||
      blockIndex < 0
    ) {
      continue
    }
    if (seen.has(entryRef)) continue
    seen.add(entryRef)
    out.push({
      entryRef,
      blockIndex,
      savedAt: typeof b.savedAt === 'number' ? b.savedAt : 0,
    })
  }
  return out.slice(0, SPEECH_BOOKMARKS_CAP)
}

function storage(): Storage | null {
  return typeof localStorage === 'undefined' ? null : localStorage
}

/** 全量书签（最新在前）。 */
export function readSpeechBookmarks(): SpeechBookmark[] {
  return normalizeSpeechBookmarks(readRaw(storage()))
}

/** 单个 entry 的书签；没有 → null。 */
export function getSpeechBookmark(entryRef: string): SpeechBookmark | null {
  return readSpeechBookmarks().find((b) => b.entryRef === entryRef) ?? null
}

/** 保存（upsert + 提到最前 + LRU 截断）。写失败静默（设备本地增强能力，
 * 不打断朗读）。 */
export function saveSpeechBookmark(entryRef: string, blockIndex: number): void {
  const store = storage()
  if (store === null || entryRef === '') return
  const rest = readSpeechBookmarks().filter((b) => b.entryRef !== entryRef)
  const next = [
    { entryRef, blockIndex, savedAt: Date.now() },
    ...rest,
  ].slice(0, SPEECH_BOOKMARKS_CAP)
  try {
    store.setItem(SPEECH_BOOKMARKS_STORAGE_KEY, JSON.stringify(next))
  } catch {
    /* 写失败不影响本会话 */
  }
}

/** 删除单个 entry 的书签（书签 chip 上的显式清除入口）。 */
export function deleteSpeechBookmark(entryRef: string): void {
  const store = storage()
  if (store === null) return
  const next = readSpeechBookmarks().filter((b) => b.entryRef !== entryRef)
  try {
    if (next.length === 0) store.removeItem(SPEECH_BOOKMARKS_STORAGE_KEY)
    else store.setItem(SPEECH_BOOKMARKS_STORAGE_KEY, JSON.stringify(next))
  } catch {
    /* 写失败不影响本会话 */
  }
}
