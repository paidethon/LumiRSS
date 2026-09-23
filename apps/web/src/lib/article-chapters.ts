/** article-chapters — N051 章节化阅读的 DOM 章节划分/可见性控制。
 *
 * 章节定义（与 ArticleToc 的 toc- id 标记体系一致）：
 * - 章节头 = .article-content 直系子代中的 h2/h3/h4 标题（标题 id 由
 *   lib/article-toc.ts 注入；无 id 的空标题也作为边界参与划分）；
 * - 章节体 = 该标题之后、下一个**同级或更高级**标题之前的全部直系块；
 * - 选中章节时，其余直系块（含章节前的导语与末章之后的尾注）打
 *   .lumi-chapter-hidden（CSS display:none !important，见 index.css）；
 * - 原文档顺序/链接/id 一概不动——退出时整体摘除标记，全文还原。
 *
 * 不足 2 个标题的文章不提供章节模式（ArticleToc 本身就不渲染），
 * 本模块不制造假章节。
 */

export const CHAPTER_HIDDEN_CLASS = 'lumi-chapter-hidden'
/** 章节可见性变化事件（ReaderPager 依赖它重测分页布局）。 */
export const CHAPTER_CHANGE_EVENT = 'lumi:chapter-change'

function isChapterHeading(node: Element): node is HTMLHeadingElement {
  return /^H[234]$/.test(node.tagName)
}

function headingLevel(node: Element): number {
  return Number(node.tagName[1])
}

export interface ChapterSection {
  /** 章节头元素（h2/h3/h4） */
  heading: HTMLElement
  /** 章节体内的直系块（不含标题本身） */
  blocks: Element[]
  /** 章节覆盖的全部直系元素（含标题） */
  members: Element[]
}

/** 在正文中找出 id 对应的章节（headingId = toc- id；找不到返回 null
 * ——正文改版时诚实返回，不猜章节）。 */
export function findChapterSection(
  container: ParentNode,
  headingId: string,
): ChapterSection | null {
  const children = container instanceof Element ? Array.from(container.children) : []
  const index = children.findIndex(
    (node) => isChapterHeading(node) && node.id === headingId,
  )
  if (index === -1) return null
  const heading = children[index] as HTMLElement
  const level = headingLevel(heading)
  const members: Element[] = [heading]
  for (let i = index + 1; i < children.length; i += 1) {
    const node = children[i]
    if (isChapterHeading(node) && headingLevel(node) <= level) break
    members.push(node)
  }
  return { heading, blocks: members.slice(1), members }
}

/** 给指定章节之外的直系块打隐藏标记（幂等）。找不到章节时不改动任何
 * 节点并返回 0（调用方据此降级为全文显示）。 */
export function applyChapterVisibility(
  container: ParentNode,
  headingId: string | null,
): number {
  if (container instanceof Element === false) return 0
  const children = Array.from(container.children)
  if (headingId === null) {
    let removed = 0
    for (const node of children) {
      if (node.classList.contains(CHAPTER_HIDDEN_CLASS)) {
        node.classList.remove(CHAPTER_HIDDEN_CLASS)
        removed += 1
      }
    }
    return removed
  }
  const section = findChapterSection(container, headingId)
  if (section === null) return 0
  let hidden = 0
  for (const node of children) {
    const inSection = section.members.includes(node)
    const marked = node.classList.contains(CHAPTER_HIDDEN_CLASS)
    if (!inSection && !marked) {
      node.classList.add(CHAPTER_HIDDEN_CLASS)
      hidden += 1
    } else if (inSection && marked) {
      node.classList.remove(CHAPTER_HIDDEN_CLASS)
    }
  }
  return hidden
}

/** 当前是否还有章节隐藏标记（防御外部改动后状态漂移）。 */
export function hasChapterHiddenBlocks(container: ParentNode): boolean {
  if (!(container instanceof Element)) return false
  return container.querySelector(`:scope .${CHAPTER_HIDDEN_CLASS}`) !== null
}

/** 派发章节变化事件（ArticleToc 换章/退出时调用；ReaderPager 监听）。 */
export function notifyChapterChange(): void {
  if (typeof document === 'undefined') return
  document.dispatchEvent(new CustomEvent(CHAPTER_CHANGE_EVENT))
}

/** 点按/锚点落点所属章节的 headingId（目标块隐藏于其它章节时用它换章）。
 * 规则：向前找最近的章节头；目标在首章之前 → 返回第一个章节头。 */
export function containingChapterId(container: ParentNode, target: Element): string | null {
  if (!(container instanceof Element)) return null
  let node: Element | null = target
  while (node !== null && node.parentElement !== container) {
    node = node.parentElement
  }
  if (node === null) return null
  const children = Array.from(container.children)
  for (let i = children.indexOf(node); i >= 0; i -= 1) {
    const candidate = children[i]
    if (isChapterHeading(candidate) && candidate.id !== '') return candidate.id
  }
  // 首章之前的内容归第一个章节（若有）
  const first = children.find((el) => isChapterHeading(el) && el.id !== '')
  return first instanceof HTMLElement ? first.id : null
}
