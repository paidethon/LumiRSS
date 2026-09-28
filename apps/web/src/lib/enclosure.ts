/** enclosure — 播放性判定（纯逻辑；bundle 拆分收口）。
 *
 * 自 components/EnclosurePlayer 抽出：Reader 只需要这一个谓词决定是否
 * 渲染播放器，原先整块播放器模块（lucide/ui 依赖）被它拖进首屏 chunk。
 * EnclosurePlayer 保留 re-export 兼容既有引用。 */

export interface EnclosureItem {
  href: string
  type?: string | null
}

/** 该 enclosure 是否可用播放器渲染（audio/* / video/*）。 */
export function isPlayableEnclosure(item: EnclosureItem): boolean {
  const kind = (item.type ?? '').toLowerCase()
  if (kind.startsWith('audio/') || kind.startsWith('video/')) return true
  // 无 type 时按扩展名保守判断
  const path = item.href.split('?')[0] ?? ''
  return /\.(mp3|m4a|aac|ogg|oga|opus|wav|mp4|m4v|webm)$/i.test(path)
}

// ---- 续播位置存储（自 EnclosurePlayer 收口至此：auth-reset 需要
// clearEnclosurePositions，但不应为清一个键拖入整个播放器模块） ----

export const ENCLOSURE_POSITIONS_KEY = 'lumirss-enclosure-positions'
export const ENCLOSURE_POSITIONS_LIMIT = 50

type PositionMap = Record<string, number>

/** 读取续播位置表（corrupted → {}）。 */
export function readEnclosurePositions(
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): PositionMap {
  if (storage === null) return {}
  try {
    const raw = storage.getItem(ENCLOSURE_POSITIONS_KEY)
    if (raw === null) return {}
    const parsed: unknown = JSON.parse(raw)
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    const out: PositionMap = {}
    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof value === 'number' && Number.isFinite(value) && value >= 0) {
        out[key] = value
      }
    }
    return out
  } catch {
    return {}
  }
}

/** 记录播放位置（写入序近似 LRU：重写 key 移到末尾；超过 50 条逐出最旧）。 */
export function recordEnclosurePosition(
  id: string,
  seconds: number,
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): void {
  if (storage === null) return
  try {
    const positions = readEnclosurePositions(storage)
    delete positions[id]
    positions[id] = Math.max(0, seconds)
    const entries = Object.entries(positions)
    const bounded = entries.slice(Math.max(0, entries.length - ENCLOSURE_POSITIONS_LIMIT))
    storage.setItem(ENCLOSURE_POSITIONS_KEY, JSON.stringify(Object.fromEntries(bounded)))
  } catch {
    // 写失败静默：续播是本地增强数据
  }
}

/** FIX-062：换账号清空续播位置（A 的收听进度不留给 B）。 */
export function clearEnclosurePositions(
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): void {
  if (storage === null) return
  try {
    storage.removeItem(ENCLOSURE_POSITIONS_KEY)
  } catch {
    /* 写失败静默 */
  }
}
