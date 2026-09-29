/** ParagraphHitsPanel — NEW-366 段落级搜索结果。
 *
 * 长文的多个命中段落分别列出（index/offset 与 F072 同字符口径）；
 * 「只保存相关片段」是显式动作：保存的片段（per-user）可删除。
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { TextQuote } from 'lucide-react'
import {
  deleteFragment,
  fetchFragments,
  fetchParagraphHits,
  saveFragment,
} from '../../api/new361'
import { Button } from '../ui/Button'

export function ParagraphHitsPanel({
  entryRef,
  query,
  onLocateParagraph,
}: {
  entryRef: string
  query: string
  onLocateParagraph?: (offset: number) => void
}) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const enabled = open && entryRef !== '' && query.trim() !== ''
  const paragraphs = useQuery({
    queryKey: ['new366', 'paragraphs', entryRef, query],
    queryFn: () => fetchParagraphHits(entryRef, query),
    enabled,
  })
  const fragments = useQuery({
    queryKey: ['new366', 'fragments', entryRef],
    queryFn: () => fetchFragments(entryRef),
    enabled: open && entryRef !== '',
  })
  const save = useMutation({
    mutationFn: (paragraph: { index: number; text: string }) =>
      saveFragment({
        entryRef,
        query,
        paragraphIndex: paragraph.index,
        text: paragraph.text,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['new366', 'fragments', entryRef] })
    },
  })
  const remove = useMutation({
    mutationFn: (id: number) => deleteFragment(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['new366', 'fragments', entryRef] })
    },
  })

  return (
    <section
      data-testid="n366-paragraphs"
      aria-label="段落级命中"
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3"
    >
      <button
        type="button"
        aria-expanded={open}
        data-testid="n366-toggle"
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-7 items-center gap-1.5 text-left text-xs font-medium text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-accent-text)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
      >
        <TextQuote aria-hidden className="size-3.5" />
        段落级命中
      </button>
      {open && (
        <>
          {paragraphs.isPending && (
            <p role="status" className="text-xs text-[var(--lumi-text-tertiary)]">
              解析中…
            </p>
          )}
          {paragraphs.isError && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">
              段落解析失败：{paragraphs.error instanceof Error ? paragraphs.error.message : '请稍后重试。'}
            </p>
          )}
          {paragraphs.data && (
            <>
              <p className="text-xs text-[var(--lumi-text-tertiary)]">
                全文 {paragraphs.data.paragraphTotal} 段，其中 {paragraphs.data.paragraphs.length} 段命中。
                {!paragraphs.data.complete && '（仅列前 20 段）'}
              </p>
              <ul className="flex flex-col gap-1.5">
                {paragraphs.data.paragraphs.map((paragraph) => (
                  <li
                    key={paragraph.index}
                    data-testid="n366-paragraph"
                    className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2"
                  >
                    <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
                      {paragraph.text}
                      {paragraph.truncatedText && '…'}
                    </p>
                    <div className="flex gap-1.5">
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={save.isPending}
                        onClick={() => save.mutate({ index: paragraph.index, text: paragraph.text })}
                      >
                        保存此片段
                      </Button>
                      {onLocateParagraph && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => onLocateParagraph(paragraph.offset)}
                        >
                          定位到段落
                        </Button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </>
          )}
          {fragments.data !== undefined && fragments.data.items.length > 0 && (
            <div className="flex flex-col gap-1">
              <p className="text-xs font-medium text-[var(--lumi-text-secondary)]">已保存片段：</p>
              <ul className="flex flex-col gap-1">
                {fragments.data.items.map((fragment) => (
                  <li
                    key={fragment.id}
                    data-testid="n366-saved-fragment"
                    className="flex items-center justify-between gap-2 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-selected)] px-2 py-1.5"
                  >
                    <span className="line-clamp-2 text-xs text-[var(--lumi-text-secondary)]">
                      {fragment.text}
                    </span>
                    <button
                      type="button"
                      aria-label={`删除片段 ${fragment.id}`}
                      disabled={remove.isPending}
                      onClick={() => remove.mutate(fragment.id)}
                      className="shrink-0 rounded-full px-1.5 text-xs text-[var(--lumi-text-tertiary)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  )
}
