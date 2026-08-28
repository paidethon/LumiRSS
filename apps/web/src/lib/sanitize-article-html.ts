/** sanitize-article-html — 应用中唯一允许调用 DOMPurify.sanitize() 的位置。
 *
 * contentHtml 来自外部 RSS feed（经 BFF 原样搬运），是不可信输入，
 * 绝不能直接进入 dangerouslySetInnerHTML。这里用 DOMPurify 的纯 HTML
 * profile 清洗，并进一步移除不属于 Reader 的交互/嵌入元素与 inline
 * style。sanitize 之后的字符串不再做任何二次修改（regex replace 等），
 * 以免破坏 sanitizer 的安全保证。
 *
 * 危险内容（<script>、on* 事件属性、javascript: 协议等）由 DOMPurify
 * 默认规则移除；不在此手写任何 URI sanitizer regex。
 */

import DOMPurify from 'dompurify'

/** Reader 正文里不属于阅读场景的元素（表单控件、嵌入框架、样式模板）。 */
const FORBID_TAGS = [
  'form',
  'input',
  'button',
  'textarea',
  'select',
  'option',
  'iframe',
  'object',
  'embed',
  'style',
  'template',
]

/** 清洗不可信的 RSS 文章 HTML，返回可安全渲染的字符串。 */
export function sanitizeArticleHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true }, // 纯 HTML：不允许 SVG / MathML 命名空间
    FORBID_TAGS,
    FORBID_ATTR: ['style'], // inline style 一律移除
  })
}
