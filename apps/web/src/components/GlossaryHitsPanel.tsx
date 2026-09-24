/** GlossaryHitsPanel — F029 术语命中（ReaderTranslation 面板内的折叠列表）。
 *
 * 显示术语/译法/命中次数；数据来自服务端预览端点（与 translation 生成
 * prompt 附加内容同一函数产出）。展开时才请求（零成本读端点也按需）。
 * N083：提供 blocks 时逐块定位 —— 每个命中附块位置（点击跳到该块）；
 * 受保护术语带「保留」标记。 */

import { useState } from 'react'
import { BookMarked } from 'lucide-react'
import { useGlossaryHits } from '../api/queries'
import type { GlossaryHitItem } from '../api/client'
import { scrollToBlock } from '../lib/linked-scroll'
import type { ArticleBlock } from '../lib/translation-blocks'

export default function GlossaryHitsPanel({
  entryRef,
  blocks = null,
}: {
  entryRef: string
  /** N083：当前正文的已编号块（提供时命中附带块位置）。 */
  blocks?: ArticleBlock[] | null
}) {
  const [open, setOpen] = useState(false)
  const hits = useGlossaryHits(entryRef, open, blocks)
  const hasLocations = (hits.data?.hits ?? []).some(
    (hit) => (hit.blockIndexes?.length ?? 0) > 0,
  )
  return (
    <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-2" data-lumi-glossary-hits="" data-lumi-find-exclude="">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex min-h-7 w-full items-center gap-1 text-xs font-medium text-[var(--lumi-text-secondary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
      >
        <BookMarked aria-hidden className="size-3.5" />
        术语命中{open ? `（${hits.data?.hits.length ?? 0}）` : ''}
      </button>
      {open ? (
        <div className="mt-1.5 border-t border-[var(--lumi-separator)] pt-1.5">
          {hits.isPending ? (
            <p className="text-xs text-[var(--lumi-text-tertiary)]">加载中…</p>
          ) : hits.isError ? (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">
              术语命中加载失败。
            </p>
          ) : (hits.data?.hits.length ?? 0) === 0 ? (
            <p className="text-xs text-[var(--lumi-text-tertiary)]">没有命中的术语。</p>
          ) : (
            <ul className="flex flex-col gap-1">
              {(hits.data?.hits ?? []).map((hit: GlossaryHitItem) => (
                <li key={hit.term} className="flex flex-col gap-0.5 text-xs">
                  <span className="flex items-baseline gap-2">
                    <span className="font-medium text-[var(--lumi-text-primary)]">{hit.term}</span>
                    <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-secondary)]">{hit.translation}</span>
                    <span className="text-[var(--lumi-text-tertiary)]">×{hit.count}</span>
                  </span>
                  {hasLocations && (hit.blockIndexes?.length ?? 0) > 0 && (
                    <span className="flex flex-wrap items-center gap-1">
                      {hit.blockIndexes?.map((index) => (
                        <button
                          key={index}
                          type="button"
                          onClick={() => {
                            const container =
                              document.querySelector<HTMLElement>('[data-reader-body]')
                            if (container !== null) scrollToBlock(container, index)
                          }}
                          className="min-h-6 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-hover)] px-1.5 text-[11px] text-[var(--lumi-text-secondary)] underline-offset-2 hover:text-[var(--lumi-accent-text)] hover:underline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                        >
                          第 {index + 1} 段
                        </button>
                      ))}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  )
}
