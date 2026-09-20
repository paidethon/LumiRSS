/** NoteLinksPanel — F080 笔记详情「引用关系」面板（Obsidian 抽屉）。
 *
 * 反向链接（点击跳转对应笔记）+ 出站链接分组（已解析/未解析）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { listNoteBacklinks, listNoteBrokenLinks } from '../api/client'
import { useObsidianNoteDetail } from '../api/queries'

export function NoteLinksPanel({ uuid }: { uuid: string }) {
  const queryClient = useQueryClient()
  const backlinks = useQuery({
    queryKey: ['obsidian-backlinks', uuid],
    queryFn: () => listNoteBacklinks(uuid),
  })
  const broken = useQuery({
    queryKey: ['obsidian-broken', uuid],
    queryFn: () => listNoteBrokenLinks(uuid),
  })
  const detail = useObsidianNoteDetail
  const openNote = useMutation({
    mutationFn: async (targetUuid: string) => {
      // 复用详情抽屉：切到目标笔记（由父层 detail 查询按 ref 拉取）
      window.dispatchEvent(new CustomEvent('lumirss-open-obsidian-note', { detail: targetUuid }))
      await queryClient.invalidateQueries({ queryKey: ['obsidian-note', targetUuid] })
      void detail
    },
  })

  const backlinkItems = backlinks.data?.items ?? []
  const brokenItems = broken.data?.items ?? []

  return (
    <section
      data-lumi-note-links=""
      aria-label="引用关系"
      className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3 text-xs"
    >
      <h4 className="text-sm font-semibold text-[var(--lumi-text-primary)]">引用关系</h4>
      <div className="mt-2">
        <h5 className="font-medium text-[var(--lumi-text-secondary)]">
          反向链接（{backlinkItems.length}）
        </h5>
        {backlinkItems.length === 0 ? (
          <p className="mt-1 text-[var(--lumi-text-tertiary)]">没有其他笔记链接到这里。</p>
        ) : (
          <ul className="mt-1 flex flex-col gap-1">
            {backlinkItems.map((b) => (
              <li key={b.fromUuid}>
                <button
                  type="button"
                  onClick={() => openNote.mutate(b.fromUuid)}
                  className="max-w-full truncate rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-2 py-0.5 text-[var(--lumi-accent-text)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                >
                  {b.title}
                  {b.alias !== null && b.alias !== undefined && b.alias !== b.title ? `（${b.alias}）` : ''}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="mt-2">
        <h5 className="font-medium text-[var(--lumi-text-secondary)]">出站链接</h5>
        {brokenItems.length === 0 ? (
          <p className="mt-1 text-[var(--lumi-text-tertiary)]">出站链接全部已解析。</p>
        ) : (
          <ul className="mt-1 flex flex-col gap-0.5">
            {brokenItems.map((b) => (
              <li key={b.raw} className="text-[var(--lumi-danger)]">
                {b.raw}（{b.reason === 'path_escaped_vault' ? '路径逃逸 vault，已拒绝' : '未解析'}）
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}
