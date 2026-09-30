/** reading-position-calibration — NEW-353 阅读位置手动校准（纯逻辑核心）。
 *
 * 跨设备恢复不准确时，用户**显式选择**章节 + 段落作为新的同步位置，
 * 而不是只能拖动滚动条。产物复用既有 reading-position 的 v1 结构
 * （ratio + anchorText）——校准的本质是把锚点从「视口顶部附近的自动
 * 捕获」换成「用户点选的段落」，恢复端（Reader.restorePosition）零改动
 * 即受益：锚点优先、ratio 回退。
 *
 * 几何（getBoundingClientRect）留在组件层；本模块只做 DOM 遍历收集、
 * 分组与纯计算。章节 = 清洗后 HTML 的 h2–h4（article-toc 注入的
 * toc-<slug> id）；无标题文章的段落归入「全文」。 */

import { captureAnchorText } from './reading-position'
import type { TocEntry } from './article-toc'

/** 校准段落收集上限（超长文诚实截断并提示，防面板渲染过载）。 */
export const CALIBRATION_PARAGRAPH_CAP = 500

export interface CalibrationParagraph {
  /** 全局序号（文档序，0 起；显示 +1）。 */
  index: number
  /** 所属章节 id（toc-<slug>；无标题文章 = null）。 */
  chapterId: string | null
  /** 所属章节标题（无 = null）。 */
  chapterTitle: string | null
  /** 锚点文本（与 reading-position.captureAnchorText 同一规范化）。 */
  anchorText: string
}

export interface CalibrationChapter {
  id: string | null
  title: string
  paragraphs: CalibrationParagraph[]
}

/** 校准段落选择器（与 reading-position.findAnchorElement 同一契约——
 * 校准产物必须能被恢复端找回）。 */
const CALIBRATION_BLOCK_SELECTOR = [
  '.lumi-reader-article p',
  '.lumi-reader-article li',
  '.lumi-reader-article pre',
  '.lumi-reader-article blockquote',
  '.lumi-reader-article h1',
  '.lumi-reader-article h2',
  '.lumi-reader-article h3',
  '.lumi-reader-article h4',
  '.lumi-reader-article h5',
  '.lumi-reader-article h6',
].join(', ')

/** 章节标题选择器（article-toc 只给 h2–h4 注入 id）。 */
const CHAPTER_HEADING_SELECTOR = '.lumi-reader-article h2[id], .lumi-reader-article h3[id], .lumi-reader-article h4[id]'

/** 收集可校准段落（含章节归属；空文本块跳过；超上限截断）。
 * article 为 null（正文未挂载）→ 空数组（调用方诚实显示不可校准）。 */
export function collectCalibrationParagraphs(article: HTMLElement | null): CalibrationParagraph[] {
  if (article === null) return []
  const headings = Array.from(article.querySelectorAll(CHAPTER_HEADING_SELECTOR))
  const headingById = new Map<string, string>()
  for (const heading of headings) {
    const id = heading.getAttribute('id')
    if (id !== null && !headingById.has(id)) {
      headingById.set(id, (heading.textContent ?? '').trim())
    }
  }
  const blocks = Array.from(article.querySelectorAll(CALIBRATION_BLOCK_SELECTOR))
  const paragraphs: CalibrationParagraph[] = []
  let currentChapterId: string | null = null
  let currentChapterTitle: string | null = null
  for (const block of blocks) {
    const id = block.getAttribute('id')
    if (id !== null && headingById.has(id)) {
      currentChapterId = id
      currentChapterTitle = headingById.get(id) ?? null
    }
    const anchorText = captureAnchorText(block)
    if (anchorText === null) continue
    paragraphs.push({
      index: paragraphs.length,
      chapterId: currentChapterId,
      chapterTitle: currentChapterTitle,
      anchorText,
    })
    if (paragraphs.length >= CALIBRATION_PARAGRAPH_CAP) break
  }
  return paragraphs
}

/** 按章节分组（保持文档序；无章节段落归入「全文」组置于最前）。 */
export function groupCalibrationByChapter(
  paragraphs: CalibrationParagraph[],
  toc: TocEntry[] = [],
): CalibrationChapter[] {
  const tocTitleById = new Map(toc.map((entry) => [entry.id, entry.text]))
  const groups: CalibrationChapter[] = []
  const indexById = new Map<string, number>()
  for (const paragraph of paragraphs) {
    const key = paragraph.chapterId ?? '__all__'
    let position = indexById.get(key)
    if (position === undefined) {
      const title =
        paragraph.chapterId !== null
          ? (tocTitleById.get(paragraph.chapterId) ?? paragraph.chapterTitle ?? paragraph.chapterId)
          : '全文（无章节）'
      groups.push({ id: paragraph.chapterId, title, paragraphs: [] })
      position = groups.length - 1
      indexById.set(key, position)
    }
    groups[position]!.paragraphs.push(paragraph)
  }
  return groups
}

/** 纯计算：校准位置的 ratio（恢复点 scrollTop / 最大可滚动量）。
 * 无滚动空间（jsdom / 短文）→ 0；恢复端此时本就落在锚点（ratio 仅回退）。 */
export function calibrationRatio(
  restoreTop: number,
  scrollHeight: number,
  clientHeight: number,
): number {
  const maxScroll = scrollHeight - clientHeight
  if (maxScroll <= 0) return 0
  return Math.min(1, Math.max(0, restoreTop / maxScroll))
}

/** 恢复点 scrollTop（与 Reader.restorePosition 的锚点落点同一公式：
 * 元素顶相对滚动容器顶 + 当前 scrollTop，再上移 12px 阅读参照）。 */
export function calibrationRestoreTop(
  elementTop: number,
  scrollerTop: number,
  scrollTop: number,
): number {
  return Math.max(0, elementTop - scrollerTop + scrollTop - 12)
}
