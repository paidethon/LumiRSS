/** NEW-291..300 邮件资料与通讯阅读 — 单一挂载点工具组合。

两级情境展开（MASTER §6）：组合折叠态零渲染零查询；展开组合后各
子工具仍是折叠态零查询——只有用户展开具体工具才发起对应请求。

诚实边界（随组说明）：
- 上传的 EML 是不可信内容：正文经净化边界入库，头部按纯文本处理；
- 本组零网络：绝不发信、不代发退订（299 只展示原文信息并记录你的
  主动打开）、不访问远程资源；
- 隐私（295/300）：遮罩与脱敏导出都是显式用户选择，原文始终私有。 */

import { useState } from 'react'
import { ImportPanel } from './ImportPanel'
import { AttachmentItemsPanel, DuplicatePanel, UnsubPanel } from './MaterialOpsPanels'
import { ExportPanel, RulePreviewPanel } from './RuleExportPanels'
import { MaskPanel, SourceMapPanel } from './SourceMaskPanels'
import { QuoteFoldPanel, ThreadPanel } from './ThreadQuotePanels'
import { SubSection } from './panel'

export function New291EmailTools() {
  const [open, setOpen] = useState(false)
  const [materialId, setMaterialId] = useState('')
  return (
    <section aria-label="邮件资料（导入 / 会话 / 引用折叠 / 来源 / 遮罩 / 附件 / 规则 / 复核 / 退订 / 导出）" className="flex flex-col gap-2">
      <button
        type="button"
        aria-expanded={open}
        data-new291-tools-toggle=""
        onClick={() => setOpen((v) => !v)}
        className="self-start text-sm text-[var(--lumi-accent)] underline underline-offset-2"
      >
        {open ? '收起邮件资料工具' : '邮件资料工具（导入 / 会话 / 折叠 / 来源 / 遮罩 / 附件 / 规则 / 复核 / 退订 / 导出）'}
      </button>
      {open && (
        <div className="flex flex-col gap-2" data-new291-tools="">
          <SubSection id="email-import" label="NEW-291 导入 EML 为资料条目（解析 / 净化 / 附件预览）">
            <ImportPanel onSelect={setMaterialId} />
          </SubSection>
          {materialId !== '' && (
            <StatusLine tone="info">
              当前选中条目：{materialId}
            </StatusLine>
          )}
          <SubSection id="email-thread" label="NEW-292 会话串联（真实字段自动 + 手动关联）">
            {materialId !== '' ? <ThreadPanel materialId={materialId} /> : <p className="text-sm text-[var(--lumi-text-tertiary)]">先在「导入」清单中选择一封邮件。</p>}
          </SubSection>
          <SubSection id="email-quotes" label="NEW-293 引用折叠（逐段展开核对）">
            {materialId !== '' ? <QuoteFoldPanel materialId={materialId} /> : <p className="text-sm text-[var(--lumi-text-tertiary)]">先在「导入」清单中选择一封邮件。</p>}
          </SubSection>
          <SubSection id="email-source-maps" label="NEW-294 订阅来源映射（地址 → 个人来源）">
            <SourceMapPanel />
          </SubSection>
          <SubSection id="email-masks" label="NEW-295 隐私遮罩（分享时隐藏，原文私有）">
            {materialId !== '' ? <MaskPanel materialId={materialId} /> : <p className="text-sm text-[var(--lumi-text-tertiary)]">先在「导入」清单中选择一封邮件。</p>}
          </SubSection>
          <SubSection id="email-attachments" label="NEW-296 附件单独入库（关系保留）">
            {materialId !== '' ? <AttachmentItemsPanel materialId={materialId} /> : <p className="text-sm text-[var(--lumi-text-tertiary)]">先在「导入」清单中选择一封邮件。</p>}
          </SubSection>
          <SubSection id="email-rules" label="NEW-297 导入规则预览（样本先行，确认后应用本批）">
            <RulePreviewPanel />
          </SubSection>
          <SubSection id="email-duplicates" label="NEW-298 重复识别复核（同 ID 不同正文，由你择留）">
            <DuplicatePanel />
          </SubSection>
          <SubSection id="email-unsub" label="NEW-299 退订信息卡（只展示，绝不代发）">
            {materialId !== '' ? <UnsubPanel materialId={materialId} /> : <p className="text-sm text-[var(--lumi-text-tertiary)]">先在「导入」清单中选择一封邮件。</p>}
          </SubSection>
          <SubSection id="email-export" label="NEW-300 脱敏导出（默认脱敏，删除清单如实）">
            {materialId !== '' ? <ExportPanel materialId={materialId} /> : <p className="text-sm text-[var(--lumi-text-tertiary)]">先在「导入」清单中选择一封邮件。</p>}
          </SubSection>
        </div>
      )}
    </section>
  )
}

function StatusLine({ tone, children }: { tone: 'info'; children: React.ReactNode }) {
  return <p className={`text-sm leading-relaxed ${tone === 'info' ? 'text-[var(--lumi-text-secondary)]' : ''}`}>{children}</p>
}
