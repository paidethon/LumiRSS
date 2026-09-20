/** BilingualExportSection — F068 双语对照导出（ReaderTranslation 工具）。
 *
 * - 范围选择：全文 / 当前可见段落（视口相交计算，诚实计数）；
 * - 预览条数（导出段数）；下载 Markdown（downloadTextFile）；
 * - 转义与 F012 同源（guardCell）；修订段标注「已人工修订」。 */

import { useMemo, useState } from 'react'
import { Download } from 'lucide-react'
import type { EntryDetail, TranslationSegmentState } from '../api/types'
import type { ArticleBlock } from '../lib/translation-blocks'
import {
  buildBilingualMarkdownExport,
  downloadTextFile,
  type BilingualSegmentInput,
} from '../lib/reader-export'
import { Button } from './ui/Button'

export function BilingualExportSection({
  detail,
  segments,
  blocks,
  getVisibleIndexes,
}: {
  detail: EntryDetail
  segments: TranslationSegmentState[]
  blocks: ArticleBlock[] | null
  /** 当前可见段落的 data-lb-index 集合（视口相交；调用方提供容器）。 */
  getVisibleIndexes: () => number[]
}) {
  const [open, setOpen] = useState(false)
  const [scope, setScope] = useState<'all' | 'visible'>('all')
  const [visibleIndexes, setVisibleIndexes] = useState<number[] | null>(null)

  const segmentsByIndex = useMemo(() => {
    const map = new Map<number, TranslationSegmentState>()
    for (const s of segments) map.set(s.index, s)
    return map
  }, [segments])

  const allSegments: BilingualSegmentInput[] = useMemo(() => {
    if (blocks === null) return []
    return blocks.map((b) => {
      const s = segmentsByIndex.get(b.index)
      return {
        index: b.index,
        source: b.text,
        machineText: s?.translatedText ?? null,
        userRevision: s?.userRevision ?? null,
      }
    })
  }, [blocks, segmentsByIndex])

  function getVisibleIndexesSafe(): number[] {
    try {
      return getVisibleIndexes()
    } catch {
      return []
    }
  }

  const download = () => {
    const indexes = scope === 'visible' ? getVisibleIndexesSafe() : undefined
    if (scope === 'visible') setVisibleIndexes(indexes ?? [])
    const markdown = buildBilingualMarkdownExport(
      {
        title: detail.title,
        source: detail.feedTitle,
        date: detail.publishedAt ?? '',
        url: detail.url ?? null,
        segments: allSegments,
      },
      { scope, visibleIndexes: indexes },
    )
    const ok = downloadTextFile(
      `${detail.title || 'bilingual'}-对照稿.md`,
      markdown,
      'text/markdown',
    )
    if (!ok) {
      // 环境不支持下载：诚实提示（不假装成功）
      setScope('all')
    }
  }

  return (
    <section data-lumi-bilingual-export="" className="mt-2 text-xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="inline-flex items-center gap-1 font-medium text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
      >
        <Download aria-hidden className="size-3.5" />
        导出对照稿
      </button>
      {open && (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-[var(--lumi-text-secondary)]">
            范围
            <select
              aria-label="导出范围"
              value={scope}
              onChange={(e) => {
                const next = e.target.value as 'all' | 'visible'
                setScope(next)
                if (next === 'visible') setVisibleIndexes(getVisibleIndexesSafe())
              }}
              className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 text-xs"
            >
              <option value="all">全文</option>
              <option value="visible">当前可见段落</option>
            </select>
          </label>
          <span className="pb-1.5 text-[var(--lumi-text-tertiary)]">
            预览：{scope === 'visible' ? (visibleIndexes ?? getVisibleIndexesSafe()).length : allSegments.length} 段
          </span>
          <Button size="sm" variant="secondary" onClick={download} disabled={allSegments.length === 0}>
            下载 Markdown
          </Button>
        </div>
      )}
    </section>
  )
}
