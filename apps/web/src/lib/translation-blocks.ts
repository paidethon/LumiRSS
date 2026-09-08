/** translation-blocks — 正文分块（双语对照的配对基础）。
 *
 * 配对依据是稳定的内容块 ID：对 sanitize 后的 DOM 按文档顺序给块级元素
 * （p/h1-h6/li/blockquote/figcaption/dd/dt）编号并写入 data-lb-index。
 * 同一 contentHtml 版本 => 同一编号序列；正文变了 ArticleContent 会产出
 * 新 HTML，编号随内容自然失效（缓存键含每块文本哈希）。
 *
 * 不翻译内容：pre / code 整块跳过；无文本的块（纯图等）跳过——它们在
 * 双语/仅译文模式下原样保留。
 *
 * 翻译结果只允许以 textContent 注入（applyOverlay），模型输出永远不进
 * HTML 渲染路径——与 ArticleContent 的 DOMPurify 边界同等重要。 */

export type ReaderViewMode = 'original' | 'bilingual' | 'translated'

export interface ArticleBlock {
  index: number
  text: string
}

const BLOCK_SELECTOR =
  'p, h1, h2, h3, h4, h5, h6, li, blockquote, figcaption, dd, dt'

export function normalizedBlockText(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

/** 给容器内的块级元素写 data-lb-index，返回按序的块文本列表。幂等。 */
export function annotateBlocks(root: HTMLElement): ArticleBlock[] {
  const candidates = Array.from(root.querySelectorAll(BLOCK_SELECTOR))
  const blocks: ArticleBlock[] = []
  let index = 0
  for (const el of candidates) {
    if (el.closest('pre')) continue
    if (el.tagName === 'CODE') continue
    // 只取"最外层"块：嵌套块（li 里的 p、blockquote 里的 p）由最外层
    // 代表整块翻译，避免一段文字被拆成多条碎片。
    const parentBlock = el.parentElement?.closest(BLOCK_SELECTOR)
    if (parentBlock && !isWrapper(parentBlock)) continue
    const text = normalizedBlockText(el.textContent ?? '')
    if (text === '') continue
    const existing = el.getAttribute('data-lb-index')
    if (existing !== null) {
      // 幂等：已编号的块复用原编号（索引只增不减）
      const known = Number(existing)
      blocks.push({ index: known, text })
      if (known >= index) index = known + 1
      continue
    }
    el.setAttribute('data-lb-index', String(index))
    blocks.push({ index, text })
    index += 1
  }
  return blocks
}

function isWrapper(el: Element): boolean {
  // 我们自己插入的配对容器不是内容块。
  return el.classList.contains('lb-pair')
}

/** 清除上一次 overlay（配对容器拆回、插入的译文节点移除、隐藏恢复）。 */
export function resetOverlay(root: HTMLElement): void {
  for (const pair of Array.from(root.querySelectorAll('.lb-pair'))) {
    const parent = pair.parentElement
    if (parent === null) continue
    while (pair.firstChild !== null) {
      parent.insertBefore(pair.firstChild, pair)
    }
    pair.remove()
  }
  for (const node of Array.from(root.querySelectorAll('[data-lb-t="1"]'))) {
    node.remove()
  }
  for (const hidden of Array.from(
    root.querySelectorAll<HTMLElement>('[data-lb-hidden="1"]'),
  )) {
    hidden.removeAttribute('data-lb-hidden')
    hidden.style.removeProperty('display')
  }
}

export interface OverlayTranslations {
  /** index → 译文（只有 success 的块）。 */
  texts: Map<number, string>
  mode: Extract<ReaderViewMode, 'bilingual' | 'translated'>
}

/** 按 mode 应用译文 overlay。
 *
 * - bilingual：桌面宽阅读区“原文左、译文右”成对（.lb-pair grid），
 *   窄屏自动退化为纵向“原文 → 译文”（单列）；列表项等嵌套块采用
 *   块内插入，保持列表语义。
 * - translated：隐藏有译文的原文块文本，在原位插入译文；媒体、
 *   代码块与未翻译块原样保留。
 * - 一律 textContent 注入。 */
export function applyOverlay(root: HTMLElement, t: OverlayTranslations): void {
  resetOverlay(root)
  const candidates = Array.from(root.querySelectorAll(BLOCK_SELECTOR))
  for (const el of candidates) {
    if (el.closest('pre')) continue
    if (el.tagName === 'CODE') continue
    if (el.closest('.lb-pair') !== null) continue
    const parentBlock = el.parentElement?.closest(BLOCK_SELECTOR)
    if (parentBlock && !isWrapper(parentBlock)) continue
    const raw = el.getAttribute('data-lb-index')
    if (raw === null) continue
    const index = Number(raw)
    const translated = t.texts.get(index)
    if (translated === undefined || translated === '') continue

    const translationNode = document.createElement('div')
    translationNode.setAttribute('data-lb-t', '1')
    translationNode.className = 'lb-translation'
    translationNode.setAttribute('data-lb-mode', t.mode)
    translationNode.textContent = translated

    const nested = parentBlock !== null && parentBlock !== undefined && !isWrapper(parentBlock)
    if (t.mode === 'bilingual' && !nested) {
      const pair = document.createElement('div')
      pair.className = 'lb-pair'
      pair.setAttribute('data-lb-pair', '1')
      el.parentElement?.insertBefore(pair, el)
      pair.appendChild(el)
      pair.appendChild(translationNode)
    } else {
      el.insertAdjacentElement('afterend', translationNode)
      if (t.mode === 'translated' && !nested) {
        el.setAttribute('data-lb-hidden', '1')
        ;(el as HTMLElement).style.display = 'none'
      }
    }
  }
}
