/** 共享的 zh-CN 日期时间格式器 — 0020 AUDIT-051。
 *
 * 此前 ReaderHeader / EntryRow / ReaderSummary / ReaderTranslation 各自
 * `new Intl.DateTimeFormat('zh-CN', { year, month, day, hour, minute })`
 * 出**完全相同**的格式器，EntryCard 用一个无年份的短格式变体。集中到此处
 * 消除重复、避免未来漂移；输出与既有实现逐字一致（选项不变）。 */

/** 完整日期时间（年/月/日 时:分）——Reader 头部、列表行、AI 摘要/翻译时间戳。 */
export const dateTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})

/** 列表卡片短格式（月/日 时:分，无年份）。 */
export const listDateTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})

/** ISO 时间戳 → 列表显示文案；缺失/无效时返回 '—'（列表行与卡片共用）。
 * （生成的 API 类型中可选字段带 undefined，一并视为缺失。） */
export function formatPublishedAt(
  value: string | null | undefined,
  formatter: Intl.DateTimeFormat = dateTimeFormatter,
): string {
  if (value === null || value === undefined) {
    return '—'
  }
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : formatter.format(date)
}

/** ISO 时间戳 → 设置页文案（备份时间、环境创建时间）；无效时返回空串。 */
export function formatTimestamp(value: string | null | undefined): string {
  if (!value) {
    return ''
  }
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : dateTimeFormatter.format(date)
}

/** F04（2026-09 移动端专项）：相对时间（列表用）。
 * 刚刚 / N 分钟前 / N 小时前 / 昨天 / M月D日；超过 7 天回退完整绝对
 * 时间（相对语义失去信息量）。无效/缺失 → '—'（与既有列表行为一致）。 */
export function formatRelativeTime(
  value: string | null | undefined,
  now: Date = new Date(),
): string {
  if (value === null || value === undefined) return '—'
  const date = new Date(value)
  const time = date.getTime()
  if (Number.isNaN(time)) return '—'
  const diffMs = now.getTime() - time
  if (diffMs < 0) return dateTimeFormatter.format(date) // 未来时间不做相对化
  const minute = 60_000
  const hour = 60 * minute
  const day = 24 * hour
  if (diffMs < minute) return '刚刚'
  if (diffMs < hour) return `${Math.floor(diffMs / minute)} 分钟前`
  if (diffMs < day) return `${Math.floor(diffMs / hour)} 小时前`
  if (diffMs < 2 * day) return '昨天'
  if (diffMs < 7 * day) return `${Math.floor(diffMs / day)} 天前`
  return dateTimeFormatter.format(date)
}

/** F04：列表时间文案（相对/绝对切换；绝对用列表短格式）。 */
export function formatListTime(
  value: string | null | undefined,
  mode: 'relative' | 'absolute',
  now: Date = new Date(),
): string {
  return mode === 'relative'
    ? formatRelativeTime(value, now)
    : formatPublishedAt(value, listDateTimeFormatter)
}
