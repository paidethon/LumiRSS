/** similar-titles — N148 相似标题区别提示（纯客户端，单结果页内）。
 *
 * 动机：聚合/转载场景下一页里常出现几乎同名的条目（同题不同源/不同
 * 时间）。提示「这些行相似但不合并」——绝不合并、绝不隐藏任何一行，
 * 只给一个 相似标题 chip + 并排对比（来源/时间/摘录）帮助区分。
 *
 * 算法：标题规范化（Unicode NFKC + casefold + 去标点/空白）后切字符
 * 二元组（bigram，对中英文都稳健），Jaccard ≥ 0.8 视为近同名。
 * 单页内两两比较（页 ≤50 行，O(n²) 可忽略）。 */

export const SIMILAR_TITLE_THRESHOLD = 0.8

/** 规范化 + bigram 集合（长度 <2 的规范形整串作为一个 token）。 */
export function titleTokens(title: string): Set<string> {
  const normalized = title
    .normalize('NFKC')
    .toLowerCase()
    .replace(/[\s\p{P}\p{S}]+/gu, '')
  const tokens = new Set<string>()
  if (normalized.length < 2) {
    if (normalized.length === 1) tokens.add(normalized)
    return tokens
  }
  for (let i = 0; i < normalized.length - 1; i += 1) {
    tokens.add(normalized.slice(i, i + 2))
  }
  return tokens
}

export function jaccardSimilarity(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 && b.size === 0) return 1
  if (a.size === 0 || b.size === 0) return 0
  let intersection = 0
  for (const token of a) {
    if (b.has(token)) intersection += 1
  }
  const union = a.size + b.size - intersection
  return intersection / union
}

export function titlesSimilar(a: string, b: string): boolean {
  return (
    jaccardSimilarity(titleTokens(a), titleTokens(b)) >= SIMILAR_TITLE_THRESHOLD
  )
}

/** 单页内相似标题分组：返回 ref → 同页其它相似行的 ref 列表（原顺序）。
 * 不构造传递闭包：A~B、B~C 但 A!~C 时，A/B 与 B/C 各自成对提示
 * （诚实按两两判定，不强行归并成一个组）。 */
export function findSimilarTitleGroups<T extends { entryRef: string; title: string }>(
  items: T[],
): Map<string, string[]> {
  const result = new Map<string, string[]>()
  const tokenized = items.map((item) => titleTokens(item.title))
  for (let i = 0; i < items.length; i += 1) {
    for (let j = i + 1; j < items.length; j += 1) {
      if (
        jaccardSimilarity(tokenized[i], tokenized[j]) < SIMILAR_TITLE_THRESHOLD
      ) {
        continue
      }
      const refI = items[i].entryRef
      const refJ = items[j].entryRef
      const listI = result.get(refI) ?? []
      const listJ = result.get(refJ) ?? []
      if (!listI.includes(refJ)) listI.push(refJ)
      if (!listJ.includes(refI)) listJ.push(refI)
      result.set(refI, listI)
      result.set(refJ, listJ)
    }
  }
  return result
}
