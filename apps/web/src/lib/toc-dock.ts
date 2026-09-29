/** toc-dock — NEW-357 移动目录停靠（纯逻辑）。
 *
 * 长文目录可暂时**停靠**为紧凑导航带：当前章节随滚动变化可见
 * （复用 ArticleToc 既有滚动跟随 followId——同一事实源，不另建监听），
 * 上一章/下一章直达；退出停靠后导航带卸载，恢复正常阅读区域。
 *
 * 停靠带与「章节模式」的浮动章节导航互斥（章节模式优先——用户显式
 * 进入的章节态优先呈现）；停靠期间阅读区域不被遮挡正文（44px 带 +
 * safe-area），阅读位置/滚动完全不动。
 */

import type { TocEntry } from './article-toc'

/** 当前停靠章节下标（followId 未命中 → 0；空 toc → -1 表示不显示）。 */
export function dockCurrentIndex(toc: TocEntry[], followId: string | null): number {
  if (toc.length === 0) return -1
  if (followId === null) return 0
  const index = toc.findIndex((entry) => entry.id === followId)
  return index === -1 ? 0 : index
}

/** 相邻章节（delta = -1 上一章 / +1 下一章）；越界 → null（按钮禁用）。 */
export function dockNeighbor(
  toc: TocEntry[],
  currentId: string | null,
  delta: 1 | -1,
): TocEntry | null {
  const index = currentId === null ? -1 : toc.findIndex((entry) => entry.id === currentId)
  if (index === -1) return null
  const next = index + delta
  if (next < 0 || next >= toc.length) return null
  return toc[next] ?? null
}

/** 停靠带章节文案（与章节导航同一口径）。 */
export function dockBandLabel(index: number, total: number, text: string): string {
  return `第 ${index + 1}/${total} 章 · ${text}`
}
