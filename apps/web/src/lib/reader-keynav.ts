/** reader-keynav — N070 纯键盘阅读定位（文章内类别跳转，纯逻辑核心）。
 *
 * 键位（固定组合——lib/custom-shortcuts 注册表只支持全局动作 id 的
 * 重绑定，不支持文章域动作；按任务口径退为固定键 + 设置开关「开启」，
 * 设备本地 readerKeyNav）：
 * - Alt+↓ / Alt+↑：在当前类别内跳到下一个 / 上一个目标（循环）；
 * - Alt+Shift+↓ / Alt+Shift+↑：切换类别（标题 → 链接 → 代码块 → 批注；
 *   Shift 反向），切换后跳到新类别的首个 / 末个目标；
 * - 类别序按会话记忆（sessionStorage，标签页内粘滞）；
 * - 跳转只滚动 + 移交焦点，绝不改已读状态。
 *
 * 守卫与全局快捷键同源（lib/keyboard-shortcuts 导出）：输入框/可编辑
 * 元素聚焦不触发；IME 组合中（shouldIgnoreKeyEvent）不触发；模态打开
 * （aria-modal）不触发。 */

import { isEditable, isModalOpen, shouldIgnoreKeyEvent } from './keyboard-shortcuts'
import { resolveAnchor, rangeFromHit, readAnnotationsForEntry, type AnnotationAnchor } from './annotations'

export const KEYNAV_SESSION_KEY = 'lumirss-keynav-category'

export type KeyNavCategoryKey = 'heading' | 'link' | 'code' | 'annotation'

export interface KeyNavCategory {
  key: KeyNavCategoryKey
  label: string
}

/** 类别固定顺序（会话粘滞的循环序）。 */
export const KEYNAV_CATEGORIES: readonly KeyNavCategory[] = [
  { key: 'heading', label: '标题' },
  { key: 'link', label: '链接' },
  { key: 'code', label: '代码块' },
  { key: 'annotation', label: '批注' },
]

export function normalizeKeyNavCategory(value: unknown): KeyNavCategoryKey {
  return KEYNAV_CATEGORIES.some((c) => c.key === value) ? (value as KeyNavCategoryKey) : 'heading'
}

/** 会话内粘滞（sessionStorage；不可用 → 默认 'heading'）。 */
export function loadKeyNavCategory(
  storage: Storage | null = typeof sessionStorage === 'undefined' ? null : sessionStorage,
): KeyNavCategoryKey {
  if (storage === null) return 'heading'
  try {
    return normalizeKeyNavCategory(storage.getItem(KEYNAV_SESSION_KEY))
  } catch {
    return 'heading'
  }
}

export function saveKeyNavCategory(
  key: KeyNavCategoryKey,
  storage: Storage | null = typeof sessionStorage === 'undefined' ? null : sessionStorage,
): void {
  if (storage === null) return
  try {
    storage.setItem(KEYNAV_SESSION_KEY, key)
  } catch {
    // 写失败静默：会话内仍以内存值为准
  }
}

/** 键位折叠（纯函数，可单测）：Alt+↑/↓ 移动；Alt+Shift+↑/↓ 换类别；
 * 其它组合 → null（不消费）。 */
export type KeyNavAction =
  | { kind: 'move'; direction: 1 | -1 }
  | { kind: 'switch'; direction: 1 | -1 }

export function keyNavEventAction(e: {
  altKey?: boolean
  shiftKey?: boolean
  key?: string
}): KeyNavAction | null {
  if (e.altKey !== true) return null
  const key = e.key?.toLowerCase()
  if (key !== 'arrowdown' && key !== 'arrowup') return null
  const direction: 1 | -1 = key === 'arrowdown' ? 1 : -1
  return e.shiftKey === true ? { kind: 'switch', direction } : { kind: 'move', direction }
}

/** 守卫链（与全局快捷键同源）：IME 组合中 / 可编辑元素聚焦 / 模态打开
 * → 不消费文章域键位。 */
export function keyNavEventAllowed(e: KeyboardEvent): boolean {
  if (shouldIgnoreKeyEvent(e)) return false
  if (isEditable(e.target)) return false
  if (isModalOpen()) return false
  return true
}

/** 目标采集排除面（与结构视图一致：装饰性/隐藏子树与批注覆盖层）。 */
const KEYNAV_EXCLUDED_SELECTOR =
  '[aria-hidden="true"], [hidden], .sr-only, [data-lumi-annotations-overlay], [data-lumi-annotations-cards]'

const CATEGORY_SELECTORS: Record<Exclude<KeyNavCategoryKey, 'annotation'>, string> = {
  heading: 'h1, h2, h3, h4, h5, h6',
  link: 'a[href]',
  code: 'pre',
}

/** 收集当前类别的跳转目标（文档序；批注类别由解析后的锚点元素注入）。 */
export function collectKeyNavTargets(
  article: Element,
  category: KeyNavCategoryKey,
  annotationElements: Element[] = [],
): Element[] {
  if (category === 'annotation') {
    return annotationElements
  }
  return Array.from(article.querySelectorAll(CATEGORY_SELECTORS[category])).filter(
    (el) => el.closest(KEYNAV_EXCLUDED_SELECTOR) === null,
  )
}

/** 由当前文章的批注缓存解析锚点 → 承载元素（文档序近似 = createdAt 升序
 * 后的批注序；锚点失效的批注诚实跳过）。 */
export function annotationTargetElements(
  article: HTMLElement,
  entryRef: string,
): Element[] {
  const out: Element[] = []
  for (const annotation of readAnnotationsForEntry(entryRef)) {
    const anchor: AnnotationAnchor = annotation.anchor
    const hit = resolveAnchor(article, anchor)
    if (hit === null) continue
    const range = rangeFromHit(article, hit)
    if (range === null) continue
    const start = range.startContainer
    const el = start.nodeType === Node.ELEMENT_NODE ? (start as Element) : start.parentElement
    if (el !== null && article.contains(el)) out.push(el)
  }
  return out
}

/** 类别内循环游标：length 0 → null；游标未定位时 ↓ 到首个、↑ 到末个。 */
export function cycleIndex(current: number, length: number, direction: 1 | -1): number | null {
  if (length <= 0) return null
  if (current < 0 || current >= length) {
    return direction === 1 ? 0 : length - 1
  }
  return (current + direction + length) % length
}

/** Alt+Shift 换类别后的新类别（固定循环序）。 */
export function switchCategory(
  current: KeyNavCategoryKey,
  direction: 1 | -1,
): KeyNavCategoryKey {
  const index = KEYNAV_CATEGORIES.findIndex((c) => c.key === current)
  const base = index === -1 ? 0 : index
  const next = (base + direction + KEYNAV_CATEGORIES.length) % KEYNAV_CATEGORIES.length
  return KEYNAV_CATEGORIES[next]!.key
}
