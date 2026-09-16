/** ArticleToc — 正文目录（pool #03）：内联折叠面板，长文快速跳转。
 *
 * - 内联 <details>：桌面/移动都不遮挡正文（区别于浮层目录），键盘
 *   可达（summary 原生焦点 + Enter 切换），无 z-index/滚动锁问题；
 * - 点击目录项 → scrollIntoView 定位到注入的标题 id（见
 *   lib/article-toc.ts：id 由清洗后 HTML 派生，重复标题去重）；
 * - 少于 2 个标题时不渲染（单标题文章无需目录）。 */

import type { TocEntry } from '../lib/article-toc'

export function ArticleToc({ toc }: { toc: TocEntry[] }) {
  if (toc.length < 2) return null
  return (
    <details className="article-toc mb-4 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3.5 py-2.5">
      <summary className="cursor-pointer select-none text-sm font-medium text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]">
        目录（{toc.length}）
      </summary>
      <ul className="mt-2 flex flex-col gap-0.5 border-t border-[var(--lumi-border)] pt-2">
        {toc.map((entry) => (
          <li
            key={entry.id}
            style={{ paddingInlineStart: `${(entry.level - 2) * 0.875}rem` }}
          >
            <button
              type="button"
              onClick={() => {
                document
                  .getElementById(entry.id)
                  ?.scrollIntoView({ block: 'start', behavior: 'smooth' })
              }}
              className={
                'w-full truncate rounded-[var(--lumi-radius-sm)] py-1 text-left text-[13px] text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:text-[var(--lumi-accent-text)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]'
              }
            >
              {entry.text}
            </button>
          </li>
        ))}
      </ul>
    </details>
  )
}

export default ArticleToc
