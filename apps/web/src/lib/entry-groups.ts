/** entry-groups — 时间线按日期分组（0010a Gate E，AC7）。
 *
 * 纯函数（可测试）：把平铺的 entry 列表切成「今天 / 昨天 / M月D日」
 * 小节；publishedAt 为 null 或解析失败归入「更早」。
 *
 * 分组是展示层行为：只在相邻条目日期变化时插入小节标题，不重排列表
 * （保持 API 的排序——最新的在前）。 */

import type { EntryListItem } from '../api/types'

export interface EntryDateGroup {
  /** 小节标题（今天 / 昨天 / M月D日 / 更早） */
  label: string
  items: EntryListItem[]
}

function dateKeyOf(publishedAt: string | null): string {
  if (publishedAt === null) return 'unknown'
  const d = new Date(publishedAt)
  if (Number.isNaN(d.getTime())) return 'unknown'
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`
}

function labelOf(key: string, now: Date): string {
  if (key === 'unknown') return '更早'
  const d = new Date(key)
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)
  if (d.getTime() === today.getTime()) return '今天'
  if (d.getTime() === yesterday.getTime()) return '昨天'
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

/** 相邻同日期条目合并为一组（不重排）。 */
export function groupEntriesByDate(entries: EntryListItem[], now: Date = new Date()): EntryDateGroup[] {
  const groups: EntryDateGroup[] = []
  for (const item of entries) {
    const key = dateKeyOf(item.publishedAt)
    const last = groups[groups.length - 1]
    if (last && last.label === labelOf(key, now)) {
      last.items.push(item)
    } else {
      groups.push({ label: labelOf(key, now), items: [item] })
    }
  }
  return groups
}
