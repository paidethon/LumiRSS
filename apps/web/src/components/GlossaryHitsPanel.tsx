/** GlossaryHitsPanel — F029 术语命中（ReaderTranslation 面板内的折叠列表）。
 *
 * 显示术语/译法/命中次数；数据来自服务端预览端点（与 translation 生成
 * prompt 附加内容同一函数产出）。展开时才请求（零成本读端点也按需）。
 */

import { useState } from 'react'
import { BookMarked } from 'lucide-react'
import { useGlossaryHits } from '../api/queries'

export default function GlossaryHitsPanel({ entryRef }: { entryRef: string }) {
  const [open, setOpen] = useState(false)
  const hits = useGlossaryHits(entryRef, open)
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
              {(hits.data?.hits ?? []).map((hit: { term: string; translation: string; count: number }) => (
                <li key={hit.term} className="flex items-baseline gap-2 text-xs">
                  <span className="font-medium text-[var(--lumi-text-primary)]">{hit.term}</span>
                  <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-secondary)]">{hit.translation}</span>
                  <span className="text-[var(--lumi-text-tertiary)]">×{hit.count}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  )
}
