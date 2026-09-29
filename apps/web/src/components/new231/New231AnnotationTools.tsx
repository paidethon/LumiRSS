/** NEW-231..240 标注侧工具组合（单一挂载点）— 批注层(234)、批量迁移(238)、
 * 引用卡片(237)、汇总阅读(233)、回复提醒(236)、重定位(232,作用于首个选中项)。 */

import { AnnotationLayersPanel } from './AnnotationLayersPanel'
import { AnnotationRepliesInbox } from './AnnotationRepliesInbox'
import { AnnotationReanchorPanel } from './AnnotationReanchorPanel'
import { AnnotationSummarySection } from './AnnotationSummarySection'
import { LayerMigrationPanel } from './LayerMigrationPanel'
import { QuoteCardComposer } from './QuoteCardComposer'

export function New231AnnotationTools({ selectedIds }: { selectedIds: Set<string> }) {
  const firstSelected = [...selectedIds][0] ?? null
  return (
    <div className="flex flex-col gap-3" data-new231-annotation-tools="">
      <AnnotationSummarySection />
      <AnnotationRepliesInbox />
      <AnnotationLayersPanel selectedIds={selectedIds} />
      {firstSelected !== null && <AnnotationReanchorPanel annotationId={firstSelected} />}
      <LayerMigrationPanel selectedIds={selectedIds} />
      <QuoteCardComposer selectedIds={selectedIds} />
    </div>
  )
}
