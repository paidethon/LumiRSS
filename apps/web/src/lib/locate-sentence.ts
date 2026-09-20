/** locateSentence — F026 摘要证据定位。
 *
 * 归一化空白（全角空格/连续空白 → 单空格）与全半角差异后做子串匹配；
 * 返回首个命中的偏移（相对归一化前原文，-1 = 未找到）。重复句取
 * 第一处；正文更新后失配返回 -1（由调用方诚实显示「未在原文定位」）。
 */

/** 归一化：全角空格→半角、连续空白折叠、全角字母数字→半角。 */
export function normalizeForMatch(input: string): string {
  return input
    .replace(/\u3000/g, ' ')
    .replace(/\s+/g, ' ')
    .replace(/[Ａ-Ｚａ-ｚ０-９]/g, (ch) =>
      String.fromCharCode(ch.charCodeAt(0) - 0xfee0),
    )
    .trim()
}

/** 在 bodyText 中定位 sentence 的首个命中；返回原文偏移或 -1。
 * 归一化逐字符对应（长度不变的全角→半角映射），所以归一化文本的
 * 命中下标即原文下标。 */
export function locateSentence(sentence: string, bodyText: string): number {
  const needle = normalizeForMatch(sentence)
  const haystack = normalizeForMatch(bodyText)
  if (needle === '' || haystack === '') return -1
  const offset = haystack.indexOf(needle)
  return offset
}

/** 取句：把摘要文本切成句级列表（中英文句末标点；保留标点）。
 * 空句剔除。 */
export function splitSentences(summaryText: string): string[] {
  const parts = summaryText
    .split(/(?<=[。！？!?.；;])/g)
    .map((part) => part.trim())
    .filter((part) => part.length > 0)
  return parts
}

/** F026 DOM 侧：在已渲染正文中定位句子（文本节点精确命中 → 段落级
 * 兜底），滚动 + 高亮 2s。命中返回 true（由调用方在失败时显示诚实
 * 「未在原文定位」徽标）。 */
export function highlightSentenceInContainer(
  container: Element,
  sentence: string,
): boolean {
  const needle = normalizeForMatch(sentence)
  if (needle === '') return false
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
  let node = walker.nextNode()
  while (node !== null) {
    const text = node.nodeValue ?? ''
    const normalized = normalizeForMatch(text)
    const at = normalized.indexOf(needle)
    if (at >= 0 && text.trim() !== '') {
      // 近似映射回原文节点偏移（归一化长度不变时一一对应；空白折叠
      // 场景按比例近似，仅影响高亮起点的微小区间）。
      const ratio = text.length / Math.max(normalized.length, 1)
      const start = Math.min(Math.floor(at * ratio), Math.max(text.length - 1, 0))
      const end = Math.min(text.length, start + Math.ceil(needle.length * ratio))
      return wrapAndHighlight(node, start, end)
    }
    node = walker.nextNode()
  }
  // 段落级兜底：命中段落整体高亮（跨内联元素时精确范围不可靠）。
  const paragraphs = container.querySelectorAll('p, li, blockquote, h1, h2, h3, h4')
  for (const p of paragraphs) {
    if (normalizeForMatch(p.textContent ?? '').includes(needle)) {
      p.classList.add('lumi-para-highlight')
      p.scrollIntoView({ block: 'center' })
      window.setTimeout(() => p.classList.remove('lumi-para-highlight'), 2000)
      return true
    }
  }
  return false
}

function wrapAndHighlight(node: Node, start: number, end: number): boolean {
  const owner = node.ownerDocument
  if (owner === null) return false
  let target: Text
  if (node.nodeType === Node.TEXT_NODE) {
    target = node as Text
  } else {
    return false
  }
  const range = owner.createRange()
  try {
    range.setStart(target, start)
    range.setEnd(target, Math.min(end, target.length))
  } catch {
    return false
  }
  const mark = owner.createElement('mark')
  mark.className = 'lumi-evidence-highlight'
  try {
    range.surroundContents(mark)
  } catch {
    mark.textContent = target.textContent?.slice(start, end) ?? ''
    return false
  }
  mark.scrollIntoView({ block: 'center' })
  window.setTimeout(() => {
    const parent = mark.parentNode
    if (parent !== null) {
      while (mark.firstChild !== null) parent.insertBefore(mark.firstChild, mark)
      parent.removeChild(mark)
      parent.normalize()
    }
  }, 2000)
  return true
}
