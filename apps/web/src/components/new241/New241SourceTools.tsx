/** NEW-241..250 原文版本、溯源与证据工具组合（单一挂载点）— 版本差异(241)、
 * 来源时间轴(242)、原始字段(243)、链接复核(244)、引文补全(245)、来源链(246)、
 * 变动关注(247)、去追踪预览(248)、许可证提示(249)、证据检查单(250)。
 *
 * 情境展开（MASTER §6）：折叠态不发起任何查询——真实首读不为这组低频
 * 考据工具付网络/渲染成本；展开后子面板才挂载。 */

import { useState } from 'react'
import { ArticleVersionsPanel } from './ArticleVersionsPanel'
import { CitationChainPanel } from './CitationChainPanel'
import { CitationFieldsPanel } from './CitationFieldsPanel'
import { ContentWatchPanel } from './ContentWatchPanel'
import { DetrackPanel } from './DetrackPanel'
import { EvidenceChecklistPanel } from './EvidenceChecklistPanel'
import { LicenseNoticePanel } from './LicenseNoticePanel'
import { LinkRecheckPanel } from './LinkRecheckPanel'
import { RawFieldsPanel } from './RawFieldsPanel'
import { SourceTimelinePanel } from './SourceTimelinePanel'
import { EmptyState } from '../ui/EmptyState'

export function New241SourceTools({ entryRef }: { entryRef: string | null }) {
  const [open, setOpen] = useState(false)
  if (entryRef === null) {
    return (
      <div
        data-new241-source-tools=""
        className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
      >
        <EmptyState
          title="原文版本与溯源工具"
          description="在文章详情打开后，这里提供版本差异、时间轴、原始字段、链接复核、引用补全、来源链、变动关注、去追踪、许可证与证据检查单。"
        />
      </div>
    )
  }
  return (
    <section aria-label="原文版本与溯源工具（NEW-241..250）" className="flex flex-col gap-3">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="self-start text-sm text-[var(--lumi-accent)] underline underline-offset-2"
      >
        {open ? '收起原文版本与溯源工具' : '原文版本与溯源工具（版本差异 / 时间轴 / 字段 / 复核 / 证据）'}
      </button>
      {open && (
        <div className="flex flex-col gap-3" data-new241-source-tools="">
          <ArticleVersionsPanel entryRef={entryRef} />
          <SourceTimelinePanel entryRef={entryRef} />
          <RawFieldsPanel entryRef={entryRef} />
          <LinkRecheckPanel entryRef={entryRef} />
          <CitationFieldsPanel entryRef={entryRef} />
          <CitationChainPanel entryRef={entryRef} />
          <ContentWatchPanel entryRef={entryRef} />
          <DetrackPanel />
          <LicenseNoticePanel />
          <EvidenceChecklistPanel />
        </div>
      )}
    </section>
  )
}
