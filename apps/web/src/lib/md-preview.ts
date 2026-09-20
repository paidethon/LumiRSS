/** md-preview — F090 笔记实时预览的最小 Markdown 渲染（安全优先）。
 *
 * 顺序即安全模型：先整体 HTML 转义（所有 `<`、`>`、`&`、引号变实体），
 * 再在【已转义文本】上做行级 Markdown 结构替换（标题/列表/粗斜体/行内
 * 代码/链接），最后仍过 sanitizeArticleHtml（DOMPurify 最终边界）。
 * 注入的 `<script>` / `onerror=` 等在第一步就失去语法，绝不可能存活。
 */

import { sanitizeArticleHtml } from './sanitize-article-html'

function escapeHtml(text: string): string {
  return text
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

/** 仅允许 http(s)（ mailto: 不预览成链接，诚实降级为纯文本）。 */
function safeHref(url: string): string | null {
  try {
    const parsed = new URL(url)
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') return parsed.toString()
    return null
  } catch {
    return null
  }
}

function renderInline(escaped: string): string {
  let out = escaped
  // 行内代码（转义后的文本上替换，不引入新实体）。
  out = out.replaceAll(/`([^`]+)`/g, '<code>$1</code>')
  // 链接：[text](url) — url 已转义，先还原实体再校验协议。
  out = out.replaceAll(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, text: string, rawUrl: string) => {
    const url = safeHref(
      rawUrl.replaceAll('&amp;', '&').replaceAll('&#39;', "'").replaceAll('&quot;', '"'),
    )
    if (url === null) return text
    const href = url.replaceAll('&', '&amp;').replaceAll('"', '&quot;')
    return `<a href="${href}" rel="noreferrer noopener" target="_blank">${text}</a>`
  })
  out = out.replaceAll(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  out = out.replaceAll(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
  return out
}

/** 极简 Markdown → 安全 HTML（标题/无序有序列表/引用/段落 + 行内）。 */
export function mdPreviewHtml(markdown: string): string {
  const lines = escapeHtml(markdown ?? '').split(/\r?\n/)
  const html: string[] = []
  let listType: 'ul' | 'ol' | null = null
  const closeList = () => {
    if (listType !== null) {
      html.push(`</${listType}>`)
      listType = null
    }
  }
  for (const line of lines) {
    const heading = /^(#{1,6})\s+(.*)$/.exec(line)
    const ulItem = /^[-*]\s+(.*)$/.exec(line.trim())
    const olItem = /^\d+[.)]\s+(.*)$/.exec(line.trim())
    const quote = /^&gt;\s?(.*)$/.exec(line)
    if (heading !== null) {
      closeList()
      const level = Math.min(heading[1]!.length, 6)
      html.push(`<h${level}>${renderInline(heading[2]!)}</h${level}>`)
    } else if (ulItem !== null) {
      if (listType !== 'ul') {
        closeList()
        html.push('<ul>')
        listType = 'ul'
      }
      html.push(`<li>${renderInline(ulItem[1]!)}</li>`)
    } else if (olItem !== null) {
      if (listType !== 'ol') {
        closeList()
        html.push('<ol>')
        listType = 'ol'
      }
      html.push(`<li>${renderInline(olItem[1]!)}</li>`)
    } else if (quote !== null) {
      closeList()
      html.push(`<blockquote>${renderInline(quote[1]!)}</blockquote>`)
    } else if (line.trim() === '') {
      closeList()
    } else {
      closeList()
      html.push(`<p>${renderInline(line)}</p>`)
    }
  }
  closeList()
  // 最终边界：即便以上替换有疏漏，DOMPurify 兜底。
  return sanitizeArticleHtml(html.join('\n'))
}
