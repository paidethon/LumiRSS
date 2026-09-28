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
 *
 * FIX-136（深色主题可读性）：作者 inline style 与表现层颜色属性
 * （font color / bgcolor / background）都在此边界统一移除——任何渲染
 * 路径都不会把原站配色带进 Reader；图片与 class 承载的语义色（代码
 * 高亮随主题）保留。见 sanitize.test 与 fix-136 测试。
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

/**
 * FIX-136：表现层颜色属性与 inline style 同罪——`<font color>` /
 * `bgcolor` / `background`（属性形态的背景图）是 HTML profile 默认
 * 放行的遗留表现属性，深色主题下作者色（如 `color="#333"`、
 * `bgcolor="white"`）同样制造不可读区块。与 FORBID_ATTR style 一并
 * 在边界移除；文本内容保留，图片（img）与 class 语义（如 shiki 代码
 * 高亮的 `.lumi-sh-*` 颜色 class——颜色随主题切换）不受影响。
 */
const FORBID_COLOR_ATTRS = ['color', 'bgcolor', 'background']

/** 清洗不可信的 RSS 文章 HTML，返回可安全渲染的字符串。 */
export function sanitizeArticleHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true }, // 纯 HTML：不允许 SVG / MathML 命名空间
    FORBID_TAGS,
    FORBID_ATTR: ['style', ...FORBID_COLOR_ATTRS], // inline style 与表现层颜色一律移除
  })
}
