/** F014 定时阅读清单（阅读预算）—— 装填算法纯函数。
 *
 * 预算装填：候选按估算分钟升序装填，直到放不下为止（不足则全收并
 * 标注 underBudget=true「估算不足预算」）；无正文的候选按 3 分钟
 * 缺省估算。清单为会话内临时范围（不写入稍后读，不持久化）。 */

import { estimateReadingTime } from './reading-time'

/** 无正文候选的缺省估算（分钟）。 */
export const DEFAULT_ESTIMATE_MINUTES = 3

export interface BudgetCandidate {
  entryRef: string
  title: string
  /** 用于估算的正文/摘要文本；null = 无估算依据 → 缺省 3 分钟。 */
  text: string | null
}

export interface BudgetItem {
  entryRef: string
  title: string
  minutes: number
}

export interface BudgetResult {
  items: BudgetItem[]
  /** 清单总估算分钟。 */
  totalMinutes: number
  /** true = 全部候选装完后仍未达到预算（估算不足预算，诚实标注）。 */
  underBudget: boolean
}

export function estimateMinutes(candidate: BudgetCandidate): number {
  if (candidate.text === null || candidate.text.trim() === '') {
    return DEFAULT_ESTIMATE_MINUTES
  }
  return estimateReadingTime(candidate.text).minutes
}

/** 按预算装填（升序贪心；同分钟按传入顺序稳定）。 */
export function buildReadingBudget(
  candidates: BudgetCandidate[],
  budgetMinutes: number,
): BudgetResult {
  const withMinutes = candidates.map((candidate) => ({
    candidate,
    minutes: estimateMinutes(candidate),
  }))
  withMinutes.sort(
    (a, b) => a.minutes - b.minutes, // Array.sort 稳定（相同分钟保持传入顺序）
  )
  const items: BudgetItem[] = []
  let total = 0
  for (const entry of withMinutes) {
    if (total + entry.minutes > budgetMinutes) continue
    items.push({
      entryRef: entry.candidate.entryRef,
      title: entry.candidate.title,
      minutes: entry.minutes,
    })
    total += entry.minutes
  }
  const filled = items.length
  return {
    items,
    totalMinutes: total,
    // 全部候选装完仍未达预算 → 诚实标注「估算不足预算」
    underBudget: filled === candidates.length && total < budgetMinutes,
  }
}
