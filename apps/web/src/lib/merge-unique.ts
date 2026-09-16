/** 多页合并按 key 去重（pool #10）：双腿独立 keyset 下同一 ref 只应
 * 出现一次；旧服务端（无 libraryCursor）每页重发同一库腿切片，去重
 * 保证新旧契约下都不出现重复卡片。 */
export function mergeUnique<T>(items: Iterable<T>, key: (item: T) => string): T[] {
  const seen = new Set<string>()
  const out: T[] = []
  for (const item of items) {
    const k = key(item)
    if (seen.has(k)) continue
    seen.add(k)
    out.push(item)
  }
  return out
}
