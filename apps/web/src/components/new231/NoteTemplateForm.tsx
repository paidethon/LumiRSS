/** NEW-235 笔记模板填空 — 为阅读记录选模板、填字段保存结构化笔记。
 * content_md（自由文本区）由服务端保证不被改写；填充是附加结构。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { getNoteTemplateFill, listNoteTemplates, putNoteTemplateFill } from '../../api/new231'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'

export function NoteTemplateForm({ noteId }: { noteId: string }) {
  const queryClient = useQueryClient()
  const [templateId, setTemplateId] = useState('')
  const [values, setValues] = useState<Record<string, string>>({})
  const [notice, setNotice] = useState<string | null>(null)

  const templates = useQuery({
    queryKey: ['new231-note-templates'],
    queryFn: ({ signal }) => listNoteTemplates(signal),
  })
  const fill = useQuery({
    queryKey: ['new231-template-fill', noteId],
    queryFn: ({ signal }) => getNoteTemplateFill(noteId, signal),
  })

  const saveMutation = useMutation({
    mutationFn: () => putNoteTemplateFill(noteId, templateId, values),
    onSuccess: async () => {
      setNotice('已保存结构化填充（自由文本区未改动）。')
      await queryClient.invalidateQueries({ queryKey: ['new231-template-fill', noteId] })
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '保存失败'),
  })

  const templateItems = templates.data?.items ?? []
  const selected = templateItems.find((item) => item.id === templateId)
  const existing = fill.data

  return (
    <section aria-label="笔记模板填空（NEW-235）" className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">模板填空</h3>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">NEW-235 · 自由文本区保留</span>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
        <label>
          模板
          <select
            aria-label="选择模板"
            value={templateId}
            onChange={(event) => {
              setTemplateId(event.target.value)
              setValues({}) // 切模板即清空未保存的草稿值（不跨模板串值）
            }}
            className="ml-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1"
          >
            <option value="">选择…</option>
            {templateItems.map((item) => (
              <option key={item.id} value={item.id}>{item.name}</option>
            ))}
          </select>
        </label>
        <Button
          size="sm"
          variant="secondary"
          disabled={templateId === '' || saveMutation.isPending}
          onClick={() => saveMutation.mutate()}
        >
          保存填充
        </Button>
      </div>

      {templates.isPending && <Skeleton className="h-8 w-full" />}
      {!templates.isPending && templateItems.length === 0 && !templates.isError && (
        <EmptyState title="还没有模板" description="先在服务端创建字段模板（如「来源类型 / 核心论断 / 待核实」）。" />
      )}

      {selected && (
        <div className="flex flex-col gap-1" aria-label="模板字段">
          {selected.fields.map((field) => (
            <label key={field.key} className="flex items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
              <span className="w-24 shrink-0">{field.label}</span>
              <input
                type="text"
                value={values[field.key] ?? ''}
                onChange={(event) => setValues((prev) => ({ ...prev, [field.key]: event.target.value }))}
                aria-label={field.label}
                className="min-w-0 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-sm"
              />
            </label>
          ))}
        </div>
      )}

      {existing && existing.templateId !== null && !selected && (
        <p className="text-xs text-[var(--lumi-text-tertiary)]" aria-label="已保存填充">
          已有填充（{Object.entries(existing.values).filter(([, v]) => v !== '').length} 个非空字段）。
        </p>
      )}

      {notice !== null && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">{notice}</p>
      )}
    </section>
  )
}
