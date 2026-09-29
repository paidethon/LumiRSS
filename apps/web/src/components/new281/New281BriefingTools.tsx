/** NEW-281..290 日报、简报与周期阅读 — 单一挂载点工具组合（工作区页）。

两级情境展开（MASTER §6）：组合折叠态零渲染零查询；展开组合后各
子工具仍是折叠态零查询——只有用户展开具体工具才发起对应请求。

诚实边界（随组说明，写进空态与页脚）：
- 编排/去重/窗口/配方/生成全部是确定性装配，零 AI、零网络依赖；
- 私有 RSS 凭据只存哈希，明文只显示一次，可随时撤销；
- EML 导出只产出文件，绝不发送邮件、不需要 SMTP 凭据；
- 历史更正只增不改不删，期次正文永不静默替换。 */

import { useState } from 'react'
import { ComposerPanel } from './ComposerPanel'
import { CorrectionPanel } from './CorrectionPanel'
import { DiagnosticsPanel } from './DiagnosticsPanel'
import { DuplicateReviewPanel } from './DuplicateReviewPanel'
import { ExportPanel } from './ExportPanel'
import { FeedPublishPanel } from './FeedPublishPanel'
import { ProvenancePanel } from './ProvenancePanel'
import { RecipePanel } from './RecipePanel'
import { SubSection } from './parts'
import { TopicsPanel } from './TopicsPanel'
import { WindowPanel } from './WindowPanel'

export function New281BriefingTools() {
  const [open, setOpen] = useState(false)
  return (
    <section
      aria-label="个人简报工作台（编排 / 去重 / 截稿 / 诊断 / 订阅 / 配方 / 来源 / 主题 / 导出 / 更正）"
      className="flex flex-col gap-2"
    >
      <button
        type="button"
        aria-expanded={open}
        data-new281-tools-toggle=""
        onClick={() => setOpen((v) => !v)}
        className="self-start text-sm text-[var(--lumi-accent)] underline underline-offset-2"
      >
        {open ? '收起个人简报工作台' : '个人简报工作台（编排 / 去重 / 截稿 / 诊断 / 订阅 / 配方 / 主题 / 导出 / 更正）'}
      </button>
      {open && (
        <div className="flex flex-col gap-2" data-new281-tools="">
          <SubSection id="composer" label="NEW-281 编排台（时间范围 / 来源 / 栏目，预览修改保存）">
            <ComposerPanel />
          </SubSection>
          <SubSection id="duplicates" label="NEW-282 去重审批（重收 / 仅列后续 / 跳过）">
            <DuplicateReviewPanel />
          </SubSection>
          <SubSection id="window" label="NEW-283 截稿窗口（时区 + 截点，迟到进下一期可调回）">
            <WindowPanel />
          </SubSection>
          <SubSection id="diagnostics" label="NEW-284 生成与缺刊诊断（缺失输入 + 执行阶段，可补后重跑）">
            <DiagnosticsPanel />
          </SubSection>
          <SubSection id="feed" label="NEW-285 私有 RSS 发布（可撤销，只含已确认期次）">
            <FeedPublishPanel />
          </SubSection>
          <SubSection id="recipes" label="NEW-286 栏目配方（顺序 + 预算 + 选择规则，可复用）">
            <RecipePanel />
          </SubSection>
          <SubSection id="provenance" label="NEW-287 人工精选标记（编辑选入 vs 规则推荐，读者可见）">
            <ProvenancePanel />
          </SubSection>
          <SubSection id="topics" label="NEW-288 跨期主题追踪（期次位置 + 后续更新链）">
            <TopicsPanel />
          </SubSection>
          <SubSection id="export" label="NEW-289 EML 文件导出（只产文件，绝不发送邮件）">
            <ExportPanel />
          </SubSection>
          <SubSection id="corrections" label="NEW-290 历史更正（追加式，不静默替换）">
            <CorrectionPanel />
          </SubSection>
          <p className="text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
            本组全部为确定性装配（零 AI、零网络依赖）；所有数据按账户隔离；EML 只产出文件不发送；
            历史更正只追加，期次正文永不静默替换。
          </p>
        </div>
      )}
    </section>
  )
}
