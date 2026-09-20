/** search-explain — F074 命中解释：matchedFields → 中文徽标 + 各字段
 * 命中词推导 + 索引新鲜度文案。
 *
 * 诚实口径：只陈述服务端 matchedFields 给出的字段与可验证的命中词；
 * 绝不显示任何相关性百分比（后端无分数，UI 不编造）。 */


export type MatchField = 'title' | 'content' | 'feed' | 'author'

export const MATCH_FIELD_LABELS: Record<MatchField, string> = {
  title: '标题',
  content: '正文',
  feed: '来源',
  author: '作者',
}

interface MatchItemLike {
  title: string
  feedTitle: string
  author?: string | null
  snippet: string
  matchedFields: string[]
}

function norm(value: string): string {
  return (value || '').toLowerCase()
}

/** 各命中字段及其命中的词（词来自查询分词；字段值可验证包含才列出）。 */
export function explainMatch(item: MatchItemLike, terms: string[]): { field: MatchField; label: string; terms: string[] }[] {
  const cleanTerms = terms.map((t) => t.trim()).filter((t) => t !== '')
  const out: { field: MatchField; label: string; terms: string[] }[] = []
  for (const field of item.matchedFields ?? []) {
    if (!(field in MATCH_FIELD_LABELS)) continue
    const typed = field as MatchField
    const value =
      typed === 'title'
        ? item.title
        : typed === 'feed'
          ? item.feedTitle
          : typed === 'author'
            ? (item.author ?? '')
            : item.snippet // 正文以 snippet 为可见证据（诚实：不引用渲染外文本）
    const matched = cleanTerms.filter((t) => norm(value).includes(norm(t)))
    if (matched.length === 0) continue
    out.push({ field: typed, label: MATCH_FIELD_LABELS[typed], terms: matched })
  }
  return out
}

/** 索引新鲜度文案：N 分钟前 / N 小时前 / 未知（诚实）。 */
export function indexFreshnessLabel(lastSyncedAt: string | null | undefined, now = Date.now()): string | null {
  if (!lastSyncedAt) return null
  const at = Date.parse(lastSyncedAt)
  if (!Number.isFinite(at)) return null
  const minutes = Math.max(0, Math.round((now - at) / 60000))
  if (minutes < 1) return '索引于刚刚'
  if (minutes < 60) return `索引于 ${minutes} 分钟前`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `索引于 ${hours} 小时前`
  return `索引于 ${Math.round(hours / 24)} 天前`
}
