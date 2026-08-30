/** sanitize-article-html — 应用中唯一允许调用 DOMPurify.sanitize() 的位置。
 *
 * contentHtml 来自外部 RSS feed（经 BFF 原样搬运），是不可信输入，
 * 绝不能直接进入 dangerouslySetInnerHTML。这里用 DOMPurify 的纯 HTML
 * profile 清洗，并进一步移除不属于 Reader 的交互/嵌入元素与 inline
 * style。
 *
 * 0012 安全模型更新：本函数是整个 presentation pipeline 的【最终】
 * 安全边界——简繁转换 / 词首强调 / 代码高亮标记等 transforms 全部
 * 发生在 sanitize 之前的 inert DOM 上（见 lib/article-pipeline.ts）；
 * 无论上游 transform 引入了什么，最终输出都必须再过一次本函数。
 * transforms 之后的输出同样不得再做任何不受控字符串修改。
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
