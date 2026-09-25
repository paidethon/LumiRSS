/** card-swipe — F08 卡片滑动手势纯逻辑（无 React/DOM 依赖，可单测）。
 *
 * 手势语义（与 lib/edge-swipe 的侧滑返回互补，互不抢占）：
 * - 起点（touchstart clientX）在屏幕左缘 24px 内的手势不处理——那是
 *   侧滑返回的领地（EdgeSwipeBack）；
 * - 跟手预览位移 = dx × 0.4，上限 ±100px（防一甩到底）；
 * - 纵向让出：|dy| > |dx| 视为滚动，不做水平预览、不提交；
 * - 提交阈值：|dx| ≥ 80px 且非纵向 → 执行 settings.cardSwipeAction
 *   对应动作（read / readLater / star），否则回弹（调用方把位移归零）。
 *
 * 动作执行与视觉反馈（背景层 + translateX）归 EntryCard / EntryRow，
 * 本模块只回答「该不该预览/提交、预览多少」三个问题。 */

/** 提交阈值（px）：水平位移达到该值时 touchend 提交动作。 */
export const CARD_SWIPE_COMMIT_PX = 80
/** 预览位移上限（px）：跟手位移 × 比例后的绝对值上限。 */
export const CARD_SWIPE_PREVIEW_MAX_PX = 100
/** 跟手比例：手指位移 → 卡片预览位移（阻尼手感）。 */
export const CARD_SWIPE_PREVIEW_RATIO = 0.4
/** 左缘排除区（px）：起点 clientX ≤ 该值的手势留给侧滑返回。 */
export const CARD_SWIPE_EDGE_EXCLUDE_PX = 24

/** 起点是否允许进入卡片滑动（屏幕左缘 24px 内让给侧滑返回）。 */
export function swipeStartAllowed(startClientX: number): boolean {
  return startClientX > CARD_SWIPE_EDGE_EXCLUDE_PX
}

/** 跟手预览位移：dx × 0.4，钳制到 ±100px。 */
export function swipePreviewOffset(dx: number): number {
  const raw = dx * CARD_SWIPE_PREVIEW_RATIO
  return Math.max(-CARD_SWIPE_PREVIEW_MAX_PX, Math.min(CARD_SWIPE_PREVIEW_MAX_PX, raw))
}

/** 纵向让出：|dy| > |dx| 视为垂直滚动手势。 */
export function swipeIsVertical(dx: number, dy: number): boolean {
  return Math.abs(dy) > Math.abs(dx)
}

/** 是否提交动作：非纵向且 |dx| 达到 80px（两个方向都算——背景层在
 * 跟手侧显示，方向只影响视觉，不影响语义）。 */
export function swipeShouldCommit(dx: number, dy: number): boolean {
  return !swipeIsVertical(dx, dy) && Math.abs(dx) >= CARD_SWIPE_COMMIT_PX
}

/** 预览背景层的不透明度（0–1）：位移越大越明显，80px 处全显。 */
export function swipePreviewOpacity(previewDx: number): number {
  return Math.min(1, Math.abs(previewDx) / CARD_SWIPE_COMMIT_PX)
}

/** 动作 id → 展示标签（EntryCard/EntryRow 背景层与 N067 练习区共用词表）。 */
export const SWIPE_ACTION_LABELS: Record<string, string> = {
  none: '无动作',
  read: '标为已读',
  readLater: '加入稍后读',
  star: '收藏',
}
