/** ProvenanceCard — F30 资料溯源卡片。
 *
 * 集中展示一篇文章的来源域元数据：来源 / 作者 / 发布时间 / 首次收录
 * 时间（FreshRSS crawl）/ 原文链接 / 可用内容版本。缺失字段诚实显示
 * 「未知」；采集时间永不冒充发布时间（两者分列）。纯展示组件——数据
 * 全部来自已加载的 EntryDetail，不发起任何额外请求。 */

import type { EntryDetail } from '../api/types'

function fmt(iso: string | null | undefined): string {
  if (!iso) return '未知'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '未知'
  const pad = (n: number) => String(n).padStart(2, '0')
  // 本地时区的确定性格式（不依赖运行环境 toLocaleString 实现）
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export default function ProvenanceCard({ detail }: { detail: EntryDetail }) {
  const contentVersion =
    detail.contentHtml && detail.contentHtml.trim() !== ''
      ? 'HTML + 纯文本（正文以清洗后的 HTML 渲染）'
      : '仅纯文本'
  return (
    <details
      className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-3 py-2 text-sm"
      data-lumi-provenance
    >
      <summary className="cursor-pointer select-none text-xs font-medium text-[var(--lumi-text-secondary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]">
        资料溯源
      </summary>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-[var(--lumi-text-tertiary)]">来源</dt>
        <dd className="text-[var(--lumi-text-primary)]">{detail.feedTitle || '未知'}</dd>
        <dt className="text-[var(--lumi-text-tertiary)]">作者</dt>
        <dd className="text-[var(--lumi-text-primary)]">{detail.author || '未知'}</dd>
        <dt className="text-[var(--lumi-text-tertiary)]">发布时间</dt>
        <dd className="text-[var(--lumi-text-primary)]">{fmt(detail.publishedAt)}</dd>
        <dt className="text-[var(--lumi-text-tertiary)]">首次收录</dt>
        <dd className="text-[var(--lumi-text-primary)]">{fmt(detail.crawledAt)}</dd>
        <dt className="text-[var(--lumi-text-tertiary)]">原文链接</dt>
        <dd className="min-w-0 break-all text-[var(--lumi-text-primary)]">
          {detail.url ? (
            <a
              href={detail.url}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="text-[var(--lumi-accent-text)] underline-offset-2 hover:underline"
            >
              {detail.url}
            </a>
          ) : (
            '未知'
          )}
        </dd>
        <dt className="text-[var(--lumi-text-tertiary)]">内容版本</dt>
        <dd className="text-[var(--lumi-text-primary)]">{contentVersion}</dd>
      </dl>
    </details>
  )
}
