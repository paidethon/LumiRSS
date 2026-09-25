/** reader-tools — Reader 工具类功能（F11–F25）的共享纯逻辑。
 *
 * 原则：几何/DOM 副作用留在组件；本模块只放可测试的常量与纯函数。
 * 所有阈值集中在此（改动需同步对应测试）。
 */

import { clamp } from './clamp'

// ---- F17 按屏翻页 ----

/** 翻页步长系数：±clientHeight × 0.9（保留上一屏的阅读参照）。 */
export const PAGE_OVERLAP_RATIO = 0.9

/** 纯计算：按屏翻页的目标 scrollTop（已钳制到 [0, maxScroll]）。
 * direction=1 下一屏；-1 上一屏。 */
export function pageTargetTop(
  scrollTop: number,
  clientHeight: number,
  maxScroll: number,
  direction: 1 | -1,
): number {
  const delta = Math.round(clientHeight * PAGE_OVERLAP_RATIO) * direction
  return clamp(scrollTop + delta, 0, Math.max(0, maxScroll))
}

/** 按指定像素滚动容器（真实浏览器走平滑滚动；无 scrollBy 的环境
 * （jsdom / 极老浏览器）直接赋值 scrollTop——行为降级不缺失）。 */
export function scrollContainerBy(container: HTMLElement, deltaPx: number): void {
  const maxScroll = Math.max(0, container.scrollHeight - container.clientHeight)
  if (typeof container.scrollBy === 'function') {
    try {
      container.scrollBy({ top: deltaPx, behavior: 'smooth' })
      return
    } catch {
      /* scrollBy 抛错（罕见实现差异）→ 落到直接赋值 */
    }
  }
  container.scrollTop = clamp(container.scrollTop + deltaPx, 0, maxScroll)
}

// ---- F18 自动滚屏 ----

export type AutoScrollSpeed = 'slow' | 'medium' | 'fast'

/** 每帧滚动像素（rAF ≈ 60fps：慢 ≈ 60px/s、中 ≈ 120px/s、快 ≈ 240px/s）。 */
export const AUTO_SCROLL_SPEEDS: Record<AutoScrollSpeed, number> = {
  slow: 1,
  medium: 2,
  fast: 4,
}

export type AutoScrollState = 'off' | 'running' | 'paused'

// ---- F25 回到顶部 ----

/** 滚动超过该值出现「回到顶部」悬浮按钮（px）。 */
export const BACK_TO_TOP_THRESHOLD_PX = 600

// ---- F16 表格展开 ----

import { maskPlainTextIfActive } from './privacy-mask'

/** scrollWidth 超出 clientWidth 该值才视为「过宽表格」（防抖动误判）。 */
export const TABLE_WIDE_EXTRA_PX = 24

// ---- F24 复制引用 ----

/** 选区引用截断长度（字）。 */
export const QUOTE_MAX_CHARS = 500

export interface QuoteInput {
  title: string
  source: string
  url: string | null
  /** 选中文本（已裁剪）；空 = 无选区，仅标题+来源+链接。 */
  quote?: string
}

/** 纯文本引用格式：标题 / 来源 / 链接（有选区时附引文）。
 * N182：遮罩开启时标题/引文先遮罩（原文绝不进剪贴板）。 */
export function buildQuotePlainText(input: QuoteInput): string {
  const title = maskPlainTextIfActive(input.title)
  const quote = maskPlainTextIfActive((input.quote ?? '').trim())
  const lines = [title, input.source]
  if (input.url !== null && input.url !== '') lines.push(input.url)
  if (quote !== '') lines.push('', quote)
  return lines.join('\n')
}

/** Markdown 引用格式：标题 / 来源 / 链接 / > 引文。（N182 同上遮罩。） */
export function buildQuoteMarkdownText(input: QuoteInput): string {
  const title = maskPlainTextIfActive(input.title)
  const quote = maskPlainTextIfActive((input.quote ?? '').trim())
  const lines = [title, input.source]
  if (input.url !== null && input.url !== '') lines.push(input.url)
  if (quote !== '') lines.push('', `> ${quote}`)
  return lines.join('\n')
}

// ---- F21 分享回退 ----

/** 无 detail.url（或不可信）时的分享/复制回退地址：
 * 当前页面地址去掉 hash（单页应用内文章状态不进 URL hash）。 */
export function fallbackShareUrl(): string {
  const href = typeof window !== 'undefined' ? window.location.href : ''
  try {
    const url = new URL(href)
    url.hash = ''
    return url.href
  } catch {
    return href
  }
}

// ---- F080 当前会话阅读时长 ----

/** 纯函数：会话时长格式化（< 1 小时 `mm:ss`，≥ 1 小时 `h:mm:ss`；
 * 负数/非有限输入按 0 处理）。显示在阅读样式（Aa）面板底部。 */
export function formatSessionDuration(elapsedMs: number): string {
  const totalSeconds = Number.isFinite(elapsedMs) && elapsedMs > 0
    ? Math.floor(elapsedMs / 1000)
    : 0
  const seconds = totalSeconds % 60
  const minutes = Math.floor(totalSeconds / 60) % 60
  const hours = Math.floor(totalSeconds / 3600)
  const pad = (n: number) => String(n).padStart(2, '0')
  return hours > 0
    ? `${hours}:${pad(minutes)}:${pad(seconds)}`
    : `${pad(minutes)}:${pad(seconds)}`
}
