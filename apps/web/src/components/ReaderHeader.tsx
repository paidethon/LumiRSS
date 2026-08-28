import type { EntryDetail } from '../api/types'
import { useEntryStateMutation } from '../api/queries'
import { safeExternalHttpUrl } from '../lib/safe-external-http-url'

const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})

function formatPublishedAt(value: string | null): string {
  if (value === null) {
    return ''
  }
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : dateFormatter.format(date)
}

/** ReaderHeader — 标题 / 来源 / 作者 / 时间 / 原文链接 + 两个显式状态按钮。
 *
 * 状态按钮用 set 语义（PATCH 目标状态，非 toggle）：按当前 Detail 状态
 * 显示相反动作。read/star 两个按钮共用同一个 useEntryStateMutation 实例；
 * 任一 mutation pending 时两个按钮都 disabled（同一篇 Entry 同时最多
 * 一个 PATCH in-flight）。 */
export default function ReaderHeader({ detail }: { detail: EntryDetail }) {
  const mutation = useEntryStateMutation()

  // url 与 contentHtml 一样来自外部 RSS，是不可信输入：
  // 只放行绝对 http/https，其余一律不渲染「打开原文」。
  const articleUrl = safeExternalHttpUrl(detail.url)
  const published = formatPublishedAt(detail.publishedAt)
  const pending = mutation.isPending

  return (
    <header className="border-b border-[var(--border)] pb-4">
      <h1 className="text-xl font-semibold leading-snug text-[var(--text)]">
        {detail.title}
      </h1>
      <p className="mt-2 text-sm text-[var(--text-muted)]">
        {detail.feedTitle}
        {detail.author !== null && <span> · {detail.author}</span>}
        {published !== '' && <span> · {published}</span>}
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={pending}
          aria-pressed={detail.read}
          onClick={() => mutation.mutate({ entryRef: detail.entryRef, patch: { read: !detail.read } })}
          className="min-h-11 rounded-md border border-[var(--border)] px-3 py-1 text-sm text-[var(--text)] transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
        >
          {pending ? '处理中…' : detail.read ? '标记为未读' : '标记为已读'}
        </button>
        <button
          type="button"
          disabled={pending}
          aria-pressed={detail.starred}
          onClick={() =>
            mutation.mutate({ entryRef: detail.entryRef, patch: { starred: !detail.starred } })
          }
          className="min-h-11 rounded-md border border-[var(--border)] px-3 py-1 text-sm text-[var(--text)] transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
        >
          {pending ? '处理中…' : detail.starred ? '取消收藏' : '收藏'}
        </button>
        {articleUrl !== null && (
          <a
            href={articleUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="min-h-11 rounded-md border border-[var(--accent)] px-3 py-1 text-sm text-[var(--accent)] transition-colors hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
          >
            打开原文
          </a>
        )}
      </div>

      {mutation.isError && (
        <p className="mt-2 text-sm text-red-600" role="alert">
          状态更新失败：{mutation.error instanceof Error ? mutation.error.message : '请稍后重试。'}
        </p>
      )}
    </header>
  )
}
