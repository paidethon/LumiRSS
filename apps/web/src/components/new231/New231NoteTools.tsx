/** NEW-231..240 笔记侧工具组合（单一挂载点）— 修订对照(231)、模板填空(235)、
 * 冲突解决器(239)、附件清单(240)。未选中笔记时给出诚实空态。 */

import { NoteAttachmentsPanel } from './NoteAttachmentsPanel'
import { NoteConflictResolver } from './NoteConflictResolver'
import { NoteTemplateForm } from './NoteTemplateForm'
import { NoteVersionsPanel } from './NoteVersionsPanel'
import { EmptyState } from '../ui/EmptyState'

export function New231NoteTools({ noteId }: { noteId: string | null }) {
  if (noteId === null) {
    return (
      <div data-new231-note-tools="" className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3">
        <EmptyState
          title="笔记工具（修订对照 / 模板 / 冲突 / 附件）"
          description="编辑某条笔记后，这里提供版本快照对比、模板填空、冲突并排解决与附件清单。"
        />
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-3" data-new231-note-tools="">
      <NoteVersionsPanel noteId={noteId} />
      <NoteTemplateForm noteId={noteId} />
      <NoteConflictResolver noteId={noteId} />
      <NoteAttachmentsPanel noteId={noteId} />
    </div>
  )
}
