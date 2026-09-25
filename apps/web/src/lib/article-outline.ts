/** article-outline — N068 辅助朗读结构检查（语义大纲提取，纯逻辑）。
 *
 * 结构视图是键盘/读屏用户的首要面板（面板本身即 AT 友好表面）：
 * - 标题树：h1–h6 文档序（跳级不建树，平铺 + level 缩进——与
 *   lib/article-toc 同语义，但范围扩大到 h1–h6 且不要求已有 id）；
 * - 装饰性/重复文本剔除：位于 sr-only / aria-hidden / [hidden] 子树的
 *   元素不进大纲；标题文本计算时同样剥离这些后代（防止图标重复文案
 *   污染大纲条目）；
 * - 结构计数：链接 / 图片 / 表格 / 代码块（同一剔除规则）；
 * - 批注数由调用方注入（读 lib/annotations 的设备本地缓存 + 服务端
 *   同步缓存，保持本模块纯 DOM）。
 *
 * 开关状态（结构视图是否展开）为设备本地偏好，key
 * `lumirss-structure-view`。 */

export const STRUCTURE_VIEW_STORAGE_KEY = 'lumirss-structure-view'

/** 装饰性/不可见子树：这些元素及其后代不参与大纲。 */
const EXCLUDED_SUBTREE_SELECTOR =
  '[aria-hidden="true"], [hidden], .sr-only, [data-lumi-annotations-overlay], [data-lumi-annotations-cards], script, style, template'

/** 元素是否位于装饰性/不可见子树内。 */
function isExcluded(el: Element): boolean {
  return el.closest(EXCLUDED_SUBTREE_SELECTOR) !== null
}

/** 标题/条目文本：剥离装饰性后代后取 textContent（连续空白归一）。 */
export function visibleText(el: Element): string {
  const clone = el.cloneNode(true) as Element
  for (const node of Array.from(clone.querySelectorAll(EXCLUDED_SUBTREE_SELECTOR))) {
    node.remove()
  }
  return (clone.textContent ?? '').replace(/\s+/g, ' ').trim()
}

export interface OutlineHeading {
  /** 唯一 key（大纲内序号；标题可能没有 id——article-toc 只给 h2–h4 注入）。 */
  key: string
  /** 既有 id（可能有）；跳转优先元素引用，id 仅作辅助。 */
  id: string | null
  text: string
  level: 1 | 2 | 3 | 4 | 5 | 6
  /** 文档序（跳转/与 DOM 对账用）。 */
  index: number
}

export interface ArticleOutline {
  headings: OutlineHeading[]
  counts: {
    links: number
    images: number
    tables: number
    codeBlocks: number
    annotations: number
  }
}

/** 从正文容器提取结构大纲（只读；不改 DOM）。 */
export function buildArticleOutline(
  container: Element,
  annotationCount: number,
): ArticleOutline {
  const headings: OutlineHeading[] = []
  Array.from(container.querySelectorAll('h1, h2, h3, h4, h5, h6')).forEach(
    (heading, index) => {
      if (isExcluded(heading)) return
      const text = visibleText(heading)
      if (text === '') return
      headings.push({
        key: `outline-${index}`,
        id: heading.id !== '' ? heading.id : null,
        text,
        level: Number(heading.tagName[1]) as 1 | 2 | 3 | 4 | 5 | 6,
        index,
      })
    },
  )
  const countVisible = (selector: string): number =>
    Array.from(container.querySelectorAll(selector)).filter((el) => !isExcluded(el)).length
  return {
    headings,
    counts: {
      links: countVisible('a[href]'),
      images: countVisible('img'),
      tables: countVisible('table'),
      codeBlocks: countVisible('pre'),
      annotations: annotationCount,
    },
  }
}

// ---- 设备本地开关状态 ----

/** 读取结构视图展开状态（corrupted → false）。 */
export function readStructureViewOpen(
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): boolean {
  if (storage === null) return false
  try {
    return storage.getItem(STRUCTURE_VIEW_STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

export function writeStructureViewOpen(
  open: boolean,
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): void {
  if (storage === null) return
  try {
    storage.setItem(STRUCTURE_VIEW_STORAGE_KEY, open ? '1' : '0')
  } catch {
    // 写失败静默：设备本地偏好
  }
}
