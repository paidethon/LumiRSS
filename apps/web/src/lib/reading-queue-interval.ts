/** reading-queue-interval — N048 连续阅读间隔（设备本地设置）。
 *
 * 取值：关(0) / 15s / 30s / 60s。只作用于今日必读队列的「下一篇」
 * 流：完成一项后出现倒计时芯片（立即 / 取消），到 0 导航到下一项。
 * 约束（契约）：
 * - 倒计时绝不后台强制跳转——取消后不再导航，卸载即终止；
 * - 绝不改写已读状态（完成 ≠ FreshRSS 已读）；
 * - 关(0) = 恢复直接切换（无芯片，不自动前进）。
 * 设备本地：localStorage 单 key，不入服务端设置（不跨设备同步）。 */

export const READING_QUEUE_INTERVAL_OPTIONS = [0, 15, 30, 60] as const

export type ReadingQueueIntervalSeconds = (typeof READING_QUEUE_INTERVAL_OPTIONS)[number]

const STORAGE_KEY = 'lumirss-reading-queue-interval'

/** 归一化：只接受集合内的值；其余回退到关(0)。 */
export function normalizeReadingQueueInterval(value: unknown): ReadingQueueIntervalSeconds {
  return (READING_QUEUE_INTERVAL_OPTIONS as readonly unknown[]).includes(value)
    ? (value as ReadingQueueIntervalSeconds)
    : 0
}

export function loadReadingQueueInterval(storage: Storage | null = defaultStorage()): ReadingQueueIntervalSeconds {
  if (storage === null) return 0
  try {
    // localStorage 只存字符串（'15'）——先转数字再校验集合。
    const raw = storage.getItem(STORAGE_KEY)
    if (raw === null) return 0
    return normalizeReadingQueueInterval(Number(raw))
  } catch {
    return 0
  }
}

export function saveReadingQueueInterval(
  value: ReadingQueueIntervalSeconds,
  storage: Storage | null = defaultStorage(),
): void {
  if (storage === null) return
  try {
    storage.setItem(STORAGE_KEY, String(normalizeReadingQueueInterval(value)))
  } catch {
    // 隐私模式等存储不可用：设置退化为会话内（不阻塞流程）。
  }
}

function defaultStorage(): Storage | null {
  return typeof localStorage === 'undefined' ? null : localStorage
}
