/** EntryNotesBacklinks — F29：来源相关笔记反向入口。
 *
 * 从文章侧显示引用它的书签/笔记（rss_item_ref 反查，等值匹配而非
 * 每请求全量扫描）；没有笔记引用时完全不渲染（零噪音）。从笔记返回
 * 原文的正向入口在书签页（打开 rssItemRef 即回到本文）。 */

import { useNotesByEntry } from '../api/queries'

export default function EntryNotesBacklinks({ entryRef }: { entryRef: string }) {
  const notes = useNotesByEntry(entryRef)
  if (notes.isPending || notes.isError) return null
  const items = notes.data?.items ?? []
  if (items.length === 0) return null
  return (
    <details
      className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-3 py-2 text-sm"
      data-lumi-notes-backlinks
    >
      <summary className="cursor-pointer select-none text-xs font-medium text-[var(--lumi-text-secondary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]">
        相关笔记（{items.length}）
      </summary>
      <ul className="mt-2 flex flex-col gap-2 border-t border-[var(--lumi-separator)] pt-2">
        {items.map((note) => (
          <li key={note.ref} className="flex flex-col gap-0.5">
            <span className="text-xs font-medium text-[var(--lumi-text-primary)]">{note.title}</span>
            {note.note ? (
              <span className="whitespace-pre-wrap text-xs text-[var(--lumi-text-secondary)]">
                {note.note}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </details>
  )
}
