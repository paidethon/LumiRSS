/** source-aliases — R03 来源显示别名（设备本地存储）。
 *
 * localStorage key `lumirss-source-aliases`：JSON 对象
 * `{ feedTitle: alias }`（Map<feedTitle, alias> 的持久化形态），上限
 * 200 条（超出时淘汰最早的条目）。
 *
 * 边界（诚实）：
 * - 只做**展示层替换**：resolveSourceAlias 返回的别名用于列表/详情的
 *   来源名显示；真实订阅名（FreshRSS truth）永不被修改；
 * - 设备本地数据，不跨设备同步；
 * - 接入点说明：EntryCard / EntryRow 等列表来源名接入由集成方完成，
 *   本模块只提供解析/读写 API。
 */

const STORAGE_KEY = 'lumirss-source-aliases'
const MAX_ALIASES = 200

/** 读取全部别名（损坏数据 → 空 Map，不抛错）。 */
export function getSourceAliases(): Map<string, string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw === null) return new Map()
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return new Map()
    const map = new Map<string, string>()
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof v === 'string' && v.trim() !== '') map.set(k, v.trim())
    }
    return map
  } catch {
    return new Map()
  }
}

function writeAll(map: Map<string, string>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(Object.fromEntries(map)))
  } catch {
    // localStorage 不可用（隐私模式等）：本次修改不落盘，会话内仍生效
  }
}

/** 解析来源显示名：有别名用别名，否则原样返回真实名。 */
export function resolveSourceAlias(feedTitle: string): string {
  if (feedTitle === '') return feedTitle
  return getSourceAliases().get(feedTitle) ?? feedTitle
}

/** 设置别名（trim 后空串视为清除；上限 200，超出淘汰最早写入条目）。
 *  返回是否写入成功（false = 别名为空且原无别名，无需写入）。 */
export function setSourceAlias(feedTitle: string, alias: string): boolean {
  const title = feedTitle.trim()
  if (title === '') return false
  const trimmed = alias.trim()
  const map = getSourceAliases()
  if (trimmed === '') {
    // 空别名 = 清除语义
    map.delete(title)
    writeAll(map)
    return true
  }
  // 重写已有键以刷新插入序（Map 保持插入序，Object.fromEntries 同）
  map.delete(title)
  map.set(title, trimmed)
  while (map.size > MAX_ALIASES) {
    const oldest = map.keys().next()
    if (oldest.done === true) break
    map.delete(oldest.value)
  }
  writeAll(map)
  return true
}

/** 清除别名（真实名不受任何影响）。 */
export function clearSourceAlias(feedTitle: string): void {
  const title = feedTitle.trim()
  if (title === '') return
  const map = getSourceAliases()
  if (!map.has(title)) return
  map.delete(title)
  writeAll(map)
}

/** 上限（设置页提示用） */
export const SOURCE_ALIAS_LIMIT = MAX_ALIASES
