import type { EntryDetail } from '../api/types'
import { sanitizeArticleHtml } from '../lib/sanitize-article-html'

/** ArticleContent — 正文渲染边界（0006 全应用唯一允许
 * dangerouslySetInnerHTML 的组件）。
 *
 * 渲染路径（Spec 冻结的三分支）：
 * 1. contentHtml 非空 → DOMPurify 清洗 → dangerouslySetInnerHTML；
 *    sanitize 之后的字符串不再做任何二次修改。
 * 2. contentHtml 为 null/空白 → contentText 纯文本（React 正常文本
 *    渲染 + pre-wrap，不包装成 HTML）。
 * 3. 两者皆空 → 「这篇文章没有可显示的正文。」（不是 Error）。 */
export default function ArticleContent({ detail }: { detail: EntryDetail }) {
  if (detail.contentHtml !== null && detail.contentHtml.trim() !== '') {
    return (
      <div
        className="article-content"
        // contentHtml 是不可信的上游 RSS HTML，必须先经过
        // sanitizeArticleHtml（DOMPurify，唯一清洗点）才能进入这里。
        dangerouslySetInnerHTML={{ __html: sanitizeArticleHtml(detail.contentHtml) }}
      />
    )
  }

  if (detail.contentText.trim() !== '') {
    return (
      <div className="article-content">
        <p className="whitespace-pre-wrap">{detail.contentText}</p>
      </div>
    )
  }

  return (
    <p className="article-content text-sm text-[var(--lumi-text-secondary)]">
      这篇文章没有可显示的正文。
    </p>
  )
}
