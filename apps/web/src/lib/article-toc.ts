/** 文章目录（pool #03）——从**清洗后**的正文 HTML 提取 h2–h4 结构。
 *
 * 契约：
 * - 输入永远是 DOMPurify 输出（ArticleContent 管线产物）；本模块只做
 *   DOM 解析 + 给标题补确定性 id，不引入任何新内容——无脚本注入面。
 * - id 形如 `toc-<slug>`，slug 由标题文本派生；重复标题追加序号
 *   （toc-标题-2）。同一篇正文多次提取结果一致（锚点稳定）。
 * - 空标题跳过；无标题文章返回空目录（不渲染面板）。
 * - 标题跳级（h2 直接到 h4）不建树，按文档顺序平铺 + level 缩进。
 * - 不改变文章原意：唯一的 DOM 修改是 heading 的 id 属性。
 */

export interface TocEntry {
  id: string
  text: string
  level: 2 | 3 | 4
}

export interface TocResult {
  /** 注入 id 后的 HTML（语义与输入一致，仅 heading 获得 id）。 */
  html: string
  toc: TocEntry[]
}

/** 标题文本 → slug：保留 CJK 与字母数字，其余归一为连字符。 */
export function headingSlug(text: string): string {
  const slug = text
    .toLowerCase()
    .replace(/[^\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}\w]+/gu, '-')
    .replace(/^-+|-+$/g, '')
  return slug === '' ? 'untitled' : slug
}

export function withHeadingIds(sanitizedHtml: string): TocResult {
  const doc = new DOMParser().parseFromString(sanitizedHtml, 'text/html')
  const headings = doc.querySelectorAll('h2, h3, h4')
  if (headings.length === 0) {
    return { html: sanitizedHtml, toc: [] }
  }
  const used = new Set<string>()
  const toc: TocEntry[] = []
  for (const heading of headings) {
    const text = (heading.textContent ?? '').replace(/\s+/g, ' ').trim()
    if (text === '') continue
    const base = `toc-${headingSlug(text)}`
    let id = base
    let counter = 2
    while (used.has(id)) {
      id = `${base}-${counter}`
      counter += 1
    }
    used.add(id)
    heading.id = id
    const level = Number(heading.tagName[1])
    if (level === 2 || level === 3 || level === 4) {
      toc.push({ id, text, level })
    }
  }
  return { html: doc.body.innerHTML, toc }
}
