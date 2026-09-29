/** NEW-271..280 AI 任务的可控运行与结果复核 — 单一挂载点工具组合。

两级情境展开（MASTER §6）：组合折叠态零渲染零查询；展开组合后各
子工具仍是折叠态零查询——只有用户展开具体工具才发起对应请求。

诚实边界（随组说明，写进空态与页脚）：
- 预览/过滤/diff 零费用（不调用 provider）；生成/试跑/批量执行是
  真实调用，费用与约束与对应单篇入口完全同口径；
- 隐私过滤是显式字段勾选，绝不声称自动识别所有秘密；
- 引用核验是字面匹配，绝不声称自动核验一切引用。 */

import { useState } from 'react'
import { AiDraftsPanel } from './AiDraftsPanel'
import { AnswerAdoptionPanel } from './AnswerAdoptionPanel'
import { BatchApprovalPanel } from './BatchApprovalPanel'
import { CitationCheckPanel } from './CitationCheckPanel'
import { InputPreviewPanel } from './InputPreviewPanel'
import { PrivacyFilterPanel } from './PrivacyFilterPanel'
import { PurposeConstraintsPanel } from './PurposeConstraintsPanel'
import { QuotaBucketsPanel } from './QuotaBucketsPanel'
import { SubSection } from './panel'
import { TaskReplayPanel } from './TaskReplayPanel'
import { TemplateTrialsPanel } from './TemplateTrialsPanel'

export function New271AiControlTools({
  entryRef,
  answerText = '',
}: {
  entryRef: string
  answerText?: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <section aria-label="AI 任务控制台（预览 / 对照 / 试跑 / 核验 / 审批 / 诊断 / 约束 / 隐私 / 采纳 / 分桶）" className="flex flex-col gap-2">
      <button
        type="button"
        aria-expanded={open}
        data-new271-tools-toggle=""
        onClick={() => setOpen((v) => !v)}
        className="self-start text-sm text-[var(--lumi-accent)] underline underline-offset-2"
      >
        {open ? '收起 AI 任务控制台' : 'AI 任务控制台（预览 / 对照 / 试跑 / 核验 / 审批 / 诊断）'}
      </button>
      {open && (
        <div className="flex flex-col gap-2" data-new271-tools="">
          <SubSection id="input-preview" label="NEW-271 输入预览（执行前看将发送的范围）">
            <InputPreviewPanel entryRef={entryRef} />
          </SubSection>
          <SubSection id="ai-drafts" label="NEW-272 草稿版本对照（不同提示方案并列）">
            <AiDraftsPanel entryRef={entryRef} />
          </SubSection>
          <SubSection id="template-trials" label="NEW-273 提示模板试运行（少量样本先行）">
            <TemplateTrialsPanel />
          </SubSection>
          <SubSection id="citation-checks" label="NEW-274 引用核验（逐条定位，未找到如实标出）">
            <CitationCheckPanel />
          </SubSection>
          <SubSection id="batch-approvals" label="NEW-275 批量任务审批单（清单 + 预算，可取消未开始项）">
            <BatchApprovalPanel entryRef={entryRef} />
          </SubSection>
          <SubSection id="task-replays" label="NEW-276 失败重放诊断（脱敏请求结构 + 两种重试）">
            <TaskReplayPanel />
          </SubSection>
          <SubSection id="purpose-constraints" label="NEW-277 模型用途约束（限定任务类型）">
            <PurposeConstraintsPanel />
          </SubSection>
          <SubSection id="privacy-filters" label="NEW-278 输入隐私过滤（显式勾选字段 + 差异预览）">
            <PrivacyFilterPanel entryRef={entryRef} />
          </SubSection>
          <SubSection id="answer-adoptions" label="NEW-279 问答结论采纳（移入笔记，保留 AI 标记）">
            <AnswerAdoptionPanel answerText={answerText} />
          </SubSection>
          <SubSection id="quota-buckets" label="NEW-280 配额分桶（按用途分配额度，不静默超额）">
            <QuotaBucketsPanel />
          </SubSection>
        </div>
      )}
    </section>
  )
}
