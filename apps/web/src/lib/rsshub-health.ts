/** N022 路由一键自检 — 纯函数（Web 侧聚合，无网络）。
 *
 * 自检卡把四个既有面（预览 / N025 最近运行 / N027 缓存年龄 / N023 依赖）
 * 的结果聚合成一张判定卡；这里的纯函数只做展示层归并，绝不猜测数据——
 * 没有数据的分区如实显示「—」。 */

import type { RssHubRouteRun } from '../api/types'

export interface RouteRunsSummary {
  total: number
  ok: number
  failed: number
}

/** N025 最近运行聚合：x/y ok（空记录 → 全 0，由调用方呈现诚实空态）。 */
export function summarizeRouteRuns(runs: readonly RssHubRouteRun[]): RouteRunsSummary {
  let ok = 0
  let failed = 0
  for (const run of runs) {
    if (run.status === 'ok') ok += 1
    else failed += 1
  }
  return { total: runs.length, ok, failed }
}

/** N027 缓存年龄文案：fresh = 刚抓取；缓存命中 = 秒龄；未知 = 「—」。 */
export function formatCacheAge(
  cache: { ageS?: number | null; fresh?: boolean } | null | undefined,
): string {
  if (cache === null || cache === undefined) return '—'
  const age = typeof cache.ageS === 'number' && Number.isFinite(cache.ageS) ? cache.ageS : null
  if (age === null) return '—'
  if (cache.fresh === true || age <= 0) return '刚抓取'
  if (age < 60) return `${Math.round(age)} 秒前`
  if (age < 3600) return `${Math.round(age / 60)} 分钟前`
  return `${Math.round(age / 3600)} 小时前`
}
