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
