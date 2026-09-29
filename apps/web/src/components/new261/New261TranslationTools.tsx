/** NEW-261..270 翻译质量与个人语言工作流（单一挂载点）— 冲突译法(261)、
 * 修订决定(262)、质量反馈(263)、能力对照(264)、预算预估(265)、优先队列(266)、
 * 保护例外(267)、引用导出(268)、语言更正(269)、完整性报告(270)。
 *
 * 情境展开（MASTER §6：高级工具按情境展开，不常驻渲染）：折叠态不发起
 * 任何查询——阅读首屏不为这些低频工作流付网络/渲染成本；展开后子面板
 * 才挂载。 */

import { useState } from 'react'
import type { ArticleBlock } from '../../lib/translation-blocks'
import type { TranslationSegmentState } from '../../api/types'
import { BudgetEstimatePanel } from './BudgetEstimatePanel'
import { CapabilityProbePanel } from './CapabilityProbePanel'
import { CompletenessPanel } from './CompletenessPanel'
import { GlossaryConflictsPanel } from './GlossaryConflictsPanel'
import { LanguageOverridePanel } from './LanguageOverridePanel'
import { PriorityQueuePanel } from './PriorityQueuePanel'
import { ProtectExceptionsPanel } from './ProtectExceptionsPanel'
import { QualityFeedbackPanel } from './QualityFeedbackPanel'
import { QuoteExportPanel } from './QuoteExportPanel'
import { RevisionDiscardPanel } from './RevisionDiscardPanel'
import { ToolSection } from './parts'

export function New261TranslationTools({
  entryRef,
  segments,
  blocks,
  feedUrl,
}: {
  entryRef: string
  segments: TranslationSegmentState[]
  blocks: ArticleBlock[] | null
  feedUrl: string | null
}) {
  const [open, setOpen] = useState(false)
  const blockInputs = blocks?.map((block) => ({ index: block.index, text: block.text })) ?? null
  const blockTexts = new Map((blocks ?? []).map((block) => [block.index, block.text]))
  return (
    <section aria-label="翻译工作流工具（NEW-261..270）" className="mt-4 flex flex-col gap-3">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="self-start text-sm text-[var(--lumi-accent)] underline underline-offset-2"
      >
        {open ? '收起翻译工作流工具' : '翻译工作流工具（冲突 / 修订 / 反馈 / 预算 / 队列 / 保护 / 导出 / 完整性）'}
      </button>
      {open && (
        <div className="flex flex-col gap-3" data-new261-translation-tools="">
          <ToolSection label="术语冲突与生效译法" itemId="NEW-261" hint="同名多义时由你定生效译法">
            <GlossaryConflictsPanel />
          </ToolSection>
          <ToolSection label="修订决定" itemId="NEW-262" hint="放弃修订可留底并可立即重翻">
            <RevisionDiscardPanel entryRef={entryRef} segments={segments} />
          </ToolSection>
          <ToolSection label="译文质量反馈" itemId="NEW-263" hint="段级漏译/误译/格式问题">
            <QualityFeedbackPanel entryRef={entryRef} segments={segments} />
          </ToolSection>
          <ToolSection label="翻译服务能力比较" itemId="NEW-264" hint="只用你填的样本">
            <CapabilityProbePanel />
          </ToolSection>
          <ToolSection label="任务预算预估" itemId="NEW-265" hint="提交前看量与估算费用">
            <BudgetEstimatePanel entryRef={entryRef} blocks={blockInputs} />
          </ToolSection>
          <ToolSection label="分段优先队列" itemId="NEW-266" hint="先翻选中段，补翻不重复收费">
            <PriorityQueuePanel entryRef={entryRef} blocks={blockInputs} />
          </ToolSection>
          <ToolSection label="专有名词保护例外" itemId="NEW-267" hint="本篇当前任务豁免">
            <ProtectExceptionsPanel entryRef={entryRef} />
          </ToolSection>
          <ToolSection label="译文引用导出" itemId="NEW-268" hint="附原文/来源/机器人工标记">
            <QuoteExportPanel entryRef={entryRef} segments={segments} blockTexts={blockTexts} />
          </ToolSection>
          <ToolSection label="识别语言更正" itemId="NEW-269" hint="只影响其后新生成">
            <LanguageOverridePanel entryRef={entryRef} feedUrl={feedUrl} />
          </ToolSection>
          <ToolSection label="翻译完整性报告" itemId="NEW-270" hint="逐段台账 + 显式补译">
            <CompletenessPanel entryRef={entryRef} blocks={blockInputs} />
          </ToolSection>
        </div>
      )}
    </section>
  )
}
