/** NEW-231..240 标注侧工具组合（单一挂载点）— 批注层(234)、批量迁移(238)、
 * 引用卡片(237)、汇总阅读(233)、回复提醒(236)、重定位(232,作用于首个选中项)。
 *
 * 情境展开（MASTER §6：高级工具按情境展开，不常驻渲染）：折叠态不发起
 * 任何查询——既有管理台容器测试与真实首屏都不为这些低频工具付网络/渲染
 * 成本；展开后子面板才挂载。 */

import { useState } from 'react'
import { AnnotationLayersPanel } from './AnnotationLayersPanel'
import { AnnotationRepliesInbox } from './AnnotationRepliesInbox'
import { AnnotationReanchorPanel } from './AnnotationReanchorPanel'
import { AnnotationSummarySection } from './AnnotationSummarySection'
import { LayerMigrationPanel } from './LayerMigrationPanel'
import { QuoteCardComposer } from './QuoteCardComposer'

export function New231AnnotationTools({ selectedIds }: { selectedIds: Set<string> }) {
  const [open, setOpen] = useState(false)
  const firstSelected = [...selectedIds][0] ?? null
  return (
    <section aria-label="标注侧工具（NEW-231..240）" className="flex flex-col gap-3">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="self-start text-sm text-[var(--lumi-accent)] underline underline-offset-2"
      >
        {open ? '收起标注侧工具' : '标注侧工具（汇总 / 提醒 / 层 / 重锚 / 迁移 / 引用卡）'}
      </button>
      {open && (
        <div className="flex flex-col gap-3" data-new231-annotation-tools="">
          <AnnotationSummarySection />
          <AnnotationRepliesInbox />
          <AnnotationLayersPanel selectedIds={selectedIds} />
          {firstSelected !== null && <AnnotationReanchorPanel annotationId={firstSelected} />}
          <LayerMigrationPanel selectedIds={selectedIds} />
          <QuoteCardComposer selectedIds={selectedIds} />
        </div>
      )}
    </section>
  )
}
