/** footnotes — F059 脚注往返阅读（pipeline 后处理，受控 DOM 变换）。
 *
 * 识别三种常见脚注模式（GFM/多说的 li.footnote、Pandoc 的
 * sup > a[href^="#fn"]、a.footnote-backref 的反向），把正文引用标记
 * 替换为受控按钮（aria-label="查看脚注 N"，键盘可达），定义内容保留
 * 在隐藏容器 `#lumi-footnote-defs`（已经 sanitize 边界，注入弹层时
 * 再次走净化）。
 *
 * 硬规则与 article-pipeline 一致：只使用 DOM API，不执行任何脚本；
 * 同一脚注多处引用各自保留返回位置（data-lumi-fn-return 唯一序号）；
 * 缺失定义 → 按钮不渲染（诚实降级）；重复 id 取首个定义。
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

/** 正文内引用标记：sup > a[href^="#fn"] / a[href^="#fn"] / sup.footnote。 */
function forEachReference(doc: Document, visit: (anchor: HTMLElement, key: string) => void): void {
  const anchors = doc.querySelectorAll('sup a[href^="#fn"], a[href^="#fn"], sup.footnote a[href^="#"]')
  anchors.forEach((node) => {
    const anchor = node as HTMLElement
    const href = anchor.getAttribute('href') ?? ''
    const key = href.replace(/^#fn(:|-)?/i, '').replace(/^#/, '')
    if (key === '') return
    visit(anchor, key)
  })
}

/** 就地变换：引用 → 受控按钮；定义收集进隐藏容器。返回定义数。 */
export function transformFootnotes(doc: Document): number {
  const defs = collectDefinitions(doc)
  if (defs.size === 0) return 0
  const container = doc.createElement('div')
  container.id = FOOTNOTE_DEFS_CONTAINER_ID
  container.hidden = true
  let returnSeq = 0
  let replaced = 0
  forEachReference(doc, (anchor, key) => {
    const def = defs.get(key)
    if (def === undefined) return // 缺失定义 → 不渲染按钮（诚实降级）
    const number = def.number
    const button = doc.createElement('button')
    button.setAttribute('type', 'button')
    button.setAttribute('aria-label', `查看脚注 ${number}`)
    button.setAttribute('data-lumi-fn-ref', String(number))
    button.setAttribute('data-lumi-fn-key', key)
    button.setAttribute('data-lumi-fn-return', String(returnSeq))
    button.textContent = String(number)
    returnSeq += 1
    anchor.replaceWith(button)
    replaced += 1
    if (container.querySelector(`[data-lumi-fn-def="${key}"]`) === null) {
      const defNode = doc.createElement('div')
      defNode.setAttribute('data-lumi-fn-def', key)
      defNode.innerHTML = def.html // 已过 sanitize 的内容；弹层注入时再净化
      container.appendChild(defNode)
    }
  })
  if (container.childElementCount > 0) {
    doc.body.appendChild(container)
  }
  return replaced
}

/** 读取指定脚注的定义 HTML（弹层展示用；调用方需再次 sanitize）。 */
export function readFootnoteDefinition(
  root: ParentNode,
  key: string,
): string | null {
  const node = root.querySelector(`#${FOOTNOTE_DEFS_CONTAINER_ID} [data-lumi-fn-def="${CSS.escape(key)}"]`)
  return node instanceof HTMLElement ? node.innerHTML : null
}
