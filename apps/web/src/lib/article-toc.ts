/** 文章目录（pool #03）——从**清洗后**的正文 HTML 提取 h2–h4 结构。
 *
 * 契约：
 * - 输入永远是 DOMPurify 输出（ArticleContent 管线产物）；本模块只做
 *   DOM 解析 + 给标题补确定性 id，不引入任何新内容——无脚本注入面。
 * - id 形如 `toc-<slug>`，slug 由标题文本派生；标题既有的源 id 原样
 *   保留（正文 <a href="#…"> 的锚点目标不悬空），仅冲突时回退去重
 *   id。重复/冲突一律追加序号（toc-标题-2）。去重以文中既有 id 播种
 *  （h2–h4 自身被保留的源 id 与被改写的旧 id 除外，h1/h5/h6 及其余
 *   元素原样保留、必须绕开）——生成的 id 绝不与文中任何元素撞车
 *  （重复 DOM id 会让 getElementById 命中错误元素，目录跳错位置）。
 *   同一篇正文多次提取结果一致（锚点稳定）。
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
  // FIX-261：去重集合以文中【既有】id 播种（本模块会改写 h2–h4 的 id，
  // 这些旧 id 不算占用；h1/h5/h6 与其余元素的 id 原样保留、必须绕开）——
  // 否则标题与既有元素撞 id（重复 DOM id 非法），getElementById 命中
  // 文档序靠前的非标题元素，目录跳错位置。
  const used = new Set<string>()
  for (const el of doc.querySelectorAll('[id]')) {
    if (el.parentElement === null) continue
    const tag = el.tagName
    if ((tag === 'H2' || tag === 'H3' || tag === 'H4') && Array.from(headings).includes(el)) {
      continue
    }
    const existing = el.id
    if (existing !== '') used.add(existing)
  }
  const toc: TocEntry[] = []
  for (const heading of headings) {
    const text = (heading.textContent ?? '').replace(/\s+/g, ' ').trim()
    if (text === '') {
      // FIX-261/267：空标题不进目录，但其既有 id 仍占位（后续生成 id
      // 绝不与文中任何元素重复）。
      const emptyId = heading.getAttribute('id')
      if (emptyId !== null && emptyId !== '') used.add(emptyId)
      continue
    }
    // FIX-267：标题既有的源 id 原样保留——正文里 <a href="#源 id">
    // 的跳转目标不悬空（此前无条件改写会让文中锚链接全部失效）。
    // 仅当源 id 与既有 id 冲突时回退 toc-slug 去重 id。
    const existingId = heading.getAttribute('id')
    let id: string
    if (existingId !== null && existingId !== '' && !used.has(existingId)) {
      id = existingId
    } else {
      const base = `toc-${headingSlug(text)}`
      id = base
      let counter = 2
      while (used.has(id)) {
        id = `${base}-${counter}`
        counter += 1
      }
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
