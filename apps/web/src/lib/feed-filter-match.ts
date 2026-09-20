/** feed-filter-match — 标题过滤规则匹配（纯逻辑；bundle 拆分收口）。
 *
 * 自 settings/FilterRulesPage 抽出：EntryList 只需要这一个纯函数，
 * 原先把整个设置页模块（react/lucide/Switch 等 UI 依赖）拖进首屏
 * chunk。FilterRulesPage 保留 re-export 兼容旧引用路径。 */

import type { FilterRule } from '../store/app-settings'

/** 返回首条命中的启用规则（feed 专属优先，全局规则兜底）；无命中 → null。 */
export function matchesFilterRules(
  title: string,
  rules: FilterRule[],
  feedId: string | null,
): FilterRule | null {
  const feedRules = rules.filter((r) => r.enabled && r.feedId !== null && r.feedId === feedId)
  const globalRules = rules.filter((r) => r.enabled && r.feedId === null)
  for (const rule of [...feedRules, ...globalRules]) {
    if (rule.type === 'keyword') {
      if (title.toLowerCase().includes(rule.keyword.toLowerCase())) return rule
    } else {
      try {
        if (new RegExp(rule.keyword, 'i').test(title)) return rule
      } catch {
        /* normalize 已保证可编译；防御 */
      }
    }
  }
  return null
}
