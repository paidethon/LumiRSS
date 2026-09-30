/** footnotes — F059 / FIX-262 脚注往返（两段式）。
 *
 * FIX-262 根因：管线的引用→受控按钮变换发生在 sanitize **之前**，而
 * DOMPurify 配置 FORBID_TAGS 含 'button'（正文清洗边界禁止任何交互
 * 控件）——按钮在最终边界被剥掉，只剩 <sup>1</sup> 裸文本：点击不可
 * 达，往返关系（data-lumi-fn-key / data-lumi-fn-return）随之丢失。
 *
 * 修复（不放松 DOMPurify，安全边界不变）：
 * 1. 管线内 `collectFootnotes(doc)`：只收集**定义**进隐藏容器
 *    `#lumi-footnote-defs`（div + data-* 可经 sanitize 存活；定义内容
 *    随整篇正文过最终边界）；正文引用标记保持为已清洗的裸锚点。
 * 2. 渲染后 `decorateFootnoteReferences(container)`：在 DOMPurify 输出
 *    的 live DOM 上把引用锚点替换为受控按钮（DOM API 构造，type/aria/
 *    data-* 全部受控常量，textContent 只写序号）——与段落复制链接
 *    按钮 / 表格展开按钮同一信任模型（渲染后装饰，幂等）。
 *
 * 往返语义：引用按钮携带 data-lumi-fn-key（定义键）与
 * data-lumi-fn-return（唯一返回序号）；弹层「返回引用」按序号找回
 * 触发节点。缺失定义 → 不装饰（诚实降级）；重复 id 取首个定义。
 */

export const FOOTNOTE_DEFS_CONTAINER_ID = 'lumi-footnote-defs'

interface FnDef {
  key: string
  number: number
  html: string
}

/** 收集定义：li[id^="fn"] / li.footnote / div.footnotes li（取首个同 id）。 */
function collectDefinitions(doc: Document): Map<string, FnDef> {
  const defs = new Map<string, FnDef>()
  const candidates = doc.querySelectorAll('li[id], li.footnote, div.footnotes li')
  let next = 1
  candidates.forEach((node) => {
    const li = node as HTMLElement
    const key = (li.id || li.getAttribute('data-fn-key') || '').replace(/^fn(:|-)?/i, '') || li.id
    if (key === '') return
    if (defs.has(key)) return // 重复 id 容错：取首个定义
    const clone = li.cloneNode(true) as HTMLElement
    clone.removeAttribute('id')
    const backref = clone.querySelector('a[href^="#fn"], a.footnote-backref, a.revfootnote')
    backref?.remove()
    defs.set(key, { key, number: next, html: clone.innerHTML })
    next += 1
  })
  return defs
}

/** 管线内变换（sanitize 之前）：把定义收进隐藏容器。定义 div 随整篇
 * 过最终边界；正文引用锚点原样保留（按钮化在渲染后装饰阶段进行，
 * 见 decorateFootnoteReferences——FORBID_TAGS 含 button，管线内造的
 * 按钮过不了最终边界，这正是 FIX-262 的根因）。返回定义数。 */
export function collectFootnotes(doc: Document): number {
  const defs = collectDefinitions(doc)
  if (defs.size === 0) return 0
  const container = doc.createElement('div')
  container.id = FOOTNOTE_DEFS_CONTAINER_ID
  container.hidden = true
  for (const def of defs.values()) {
    const defNode = doc.createElement('div')
    defNode.setAttribute('data-lumi-fn-def', def.key)
    defNode.innerHTML = def.html // 弹层注入时调用方还会再净化一次
    container.appendChild(defNode)
  }
  doc.body.appendChild(container)
  return defs.size
}

/** 渲染后装饰（幂等，decorateCodeCopyButtons 同一模式）：在已清洗的
 * live DOM 上把正文引用锚点替换为受控按钮（键盘可达 + aria-label +
 * 往返 data 属性）。定义缺失的引用保持锚点原样（诚实降级）。 */
export function decorateFootnoteReferences(container: HTMLElement): void {
  const anchors = container.querySelectorAll(
    'sup a[href^="#fn"], a[href^="#fn"], sup.footnote a[href^="#"]',
  )
  let returnSeq = 0
  anchors.forEach((node) => {
    const anchor = node as HTMLElement
    const href = anchor.getAttribute('href') ?? ''
    const key = href.replace(/^#fn(:|-)?/i, '').replace(/^#/, '')
    if (key === '') return
    const defNode = container.querySelector(
      `#${FOOTNOTE_DEFS_CONTAINER_ID} [data-lumi-fn-def="${CSS.escape(key)}"]`,
    )
    if (defNode === null) return // 缺失定义 → 不装饰（诚实降级）
    // 定义序号 = 收集顺序（与 collectFootnotes 编号一致）
    const number =
      Array.from(
        container.querySelectorAll(`#${FOOTNOTE_DEFS_CONTAINER_ID} [data-lumi-fn-def]`),
      ).indexOf(defNode) + 1
    const button = container.ownerDocument.createElement('button')
    button.setAttribute('type', 'button')
    button.setAttribute('aria-label', `查看脚注 ${number}`)
    button.setAttribute('data-lumi-fn-ref', String(number))
    button.setAttribute('data-lumi-fn-key', key)
    button.setAttribute('data-lumi-fn-return', String(returnSeq))
    button.textContent = String(number)
    returnSeq += 1
    anchor.replaceWith(button)
  })
}

/** 读取指定脚注的定义 HTML（弹层展示用；调用方需再次 sanitize）。 */
export function readFootnoteDefinition(
  root: ParentNode,
  key: string,
): string | null {
  const node = root.querySelector(`#${FOOTNOTE_DEFS_CONTAINER_ID} [data-lumi-fn-def="${CSS.escape(key)}"]`)
  return node instanceof HTMLElement ? node.innerHTML : null
}
