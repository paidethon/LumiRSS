/** NEW-258 研究大纲编排 — 章节/素材上移下移 + 跨章分配 + Markdown 草稿。
 *
 * 诚实标注：编排是「上移/下移 + 分配」，不是拖拽；quote 必须带出处。
 * 草稿由服务端只读生成，前端仅展示。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  addOutlineItem,
  addOutlineSection,
  assignOutlineItem,
  getOutline,
  getOutlineDraft,
  moveOutlineItem,
  moveOutlineSection,
  type OutlineItem,
} from '../../api/new251'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { ErrorLine, NoticeLine, SelectField, TextField } from './parts'

const KIND_LABELS: Record<OutlineItem['kind'], string> = {
  quote: '引文',
  note: '笔记',
  summary: '小结',
}

function ItemRow({
  item,
  sections,
  onMove,
  onAssign,
  busy,
}: {
  item: OutlineItem
  sections: { id: string; title: string }[]
  onMove: (id: string, direction: 'up' | 'down') => void
  onAssign: (id: string, targetSectionId: string) => void
  busy: boolean
}) {
  const [direction, setDirection] = useState<'up' | 'down'>('up')
  const [target, setTarget] = useState(sections[0]?.id ?? '')
  return (
    <li data-new258-item={item.id} className="flex flex-col gap-1.5 border-t border-[var(--lumi-border)] pt-1.5">
      <p className="text-xs text-[var(--lumi-text-primary)]">
        <span className="text-[var(--lumi-text-tertiary)]">[{KIND_LABELS[item.kind]}]</span>{' '}
        {item.content}
        {item.citation !== null && (
          <span className="text-[var(--lumi-text-tertiary)]">（{item.citation}）</span>
        )}
      </p>
      <div className="flex flex-wrap items-end gap-1.5">
        <Button size="sm" variant="ghost" onClick={() => onMove(item.id, 'up')} disabled={busy}>
          上移
        </Button>
        <Button size="sm" variant="ghost" onClick={() => onMove(item.id, 'down')} disabled={busy}>
          下移
        </Button>
        <SelectField
          label="移向章节"
          value={target}
          onChange={setTarget}
          options={sections.map((section) => ({ value: section.id, label: section.title }))}
        />
        <Button size="sm" variant="ghost" onClick={() => setDirection(direction === 'up' ? 'down' : 'up')} className="hidden">
          切换
        </Button>
        <Button size="sm" variant="ghost" onClick={() => onAssign(item.id, target)} disabled={busy || target === item.sectionId}>
          分配到该章
        </Button>
      </div>
    </li>
  )
}

export function OutlinePanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const [sectionTitle, setSectionTitle] = useState('')
  const [itemKind, setItemKind] = useState<'quote' | 'note' | 'summary'>('note')
  const [itemContent, setItemContent] = useState('')
  const [itemCitation, setItemCitation] = useState('')
  const [targetSection, setTargetSection] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  const [draft, setDraft] = useState<string | null>(null)

  const outline = useQuery({
    queryKey: ['new258-outline', projectId],
    queryFn: ({ signal }) => getOutline(projectId, signal),
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['new258-outline', projectId] })

  const report = (message: string) => setNotice(message)

  const addSection = useMutation({
    mutationFn: () => addOutlineSection(projectId, sectionTitle),
    onSuccess: async () => {
      setSectionTitle('')
      report('章节已添加。')
      await invalidate()
    },
    onError: (error) => report(error instanceof Error ? error.message : '添加失败'),
  })
  const addItem = useMutation({
    mutationFn: () =>
      addOutlineItem(targetSection, {
        kind: itemKind,
        content: itemContent,
        citation: itemCitation || undefined,
      }),
    onSuccess: async () => {
      setItemContent('')
      setItemCitation('')
      report('素材已放入章节。')
      await invalidate()
    },
    onError: (error) => report(error instanceof Error ? error.message : '添加失败'),
  })
  const moveItem = useMutation({
    mutationFn: (args: { id: string; direction: 'up' | 'down' }) => moveOutlineItem(args.id, args.direction),
    onSuccess: async (result) => {
      report(result.moved === 1 ? '顺序已更新。' : result.note)
      await invalidate()
    },
  })
  const moveSection = useMutation({
    mutationFn: (args: { id: string; direction: 'up' | 'down' }) => moveOutlineSection(args.id, args.direction),
    onSuccess: async (result) => {
      report(result.moved === 1 ? '章节顺序已更新。' : result.note)
      await invalidate()
    },
  })
  const assign = useMutation({
    mutationFn: (args: { id: string; targetSectionId: string }) => assignOutlineItem(args.id, args.targetSectionId),
    onSuccess: async () => {
      report('素材已分配到目标章节。')
      await invalidate()
    },
    onError: (error) => report(error instanceof Error ? error.message : '分配失败'),
  })
  const draftQuery = useQuery({
    queryKey: ['new258-outline-draft', projectId],
    queryFn: ({ signal }) => getOutlineDraft(projectId, signal),
    enabled: draft !== null,
  })

  const sections = outline.data?.sections ?? []
  return (
    <div data-new258-outline="" className="flex flex-col gap-3">
      <p className="text-xs text-[var(--lumi-text-tertiary)]">
        编排方式诚实标注：上移/下移 + 跨章分配（非拖拽）。
      </p>
      <div className="flex items-end gap-2">
        <div className="min-w-40 flex-1">
          <TextField label="新章节标题" value={sectionTitle} onChange={setSectionTitle} />
        </div>
        <Button size="sm" onClick={() => addSection.mutate()} disabled={addSection.isPending}>
          添加章节
        </Button>
      </div>
      <div className="flex flex-wrap items-end gap-2 border-t border-[var(--lumi-border)] pt-3">
        <SelectField
          label="素材类型"
          value={itemKind}
          onChange={(value) => setItemKind(value as 'quote' | 'note' | 'summary')}
          options={[
            { value: 'quote', label: '引文（须带出处）' },
            { value: 'note', label: '笔记' },
            { value: 'summary', label: '小结' },
          ]}
        />
        <SelectField
          label="放入章节"
          value={targetSection}
          onChange={setTargetSection}
          options={[{ value: '', label: '选择章节…' }, ...sections.map((section) => ({ value: section.id, label: section.title }))]}
        />
        <div className="min-w-48 flex-1">
          <TextField label="素材内容" value={itemContent} onChange={setItemContent} />
        </div>
        <div className="min-w-32 flex-1">
          <TextField label="出处（引文必填）" value={itemCitation} onChange={setItemCitation} />
        </div>
        <Button size="sm" onClick={() => addItem.mutate()} disabled={addItem.isPending || targetSection === ''}>
          放入素材
        </Button>
      </div>
      <NoticeLine notice={notice} />
      <ErrorLine error={outline.error} />
      {outline.data !== undefined && sections.length === 0 && (
        <EmptyState title="大纲为空" description="先建章节，再把引文、笔记与小结放进去。" />
      )}
      <ol className="flex flex-col gap-2">
        {sections.map((section) => (
          <li key={section.id} data-new258-section={section.id} className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium text-[var(--lumi-text-primary)]">{section.title}</p>
              <span className="flex gap-1">
                <Button size="sm" variant="ghost" onClick={() => moveSection.mutate({ id: section.id, direction: 'up' })} disabled={moveSection.isPending}>
                  章节上移
                </Button>
                <Button size="sm" variant="ghost" onClick={() => moveSection.mutate({ id: section.id, direction: 'down' })} disabled={moveSection.isPending}>
                  章节下移
                </Button>
              </span>
            </div>
            {section.items.length === 0 ? (
              <p className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">（本章暂无素材）</p>
            ) : (
              <ul className="mt-1">
                {section.items.map((item) => (
                  <ItemRow
                    key={item.id}
                    item={item}
                    sections={sections.map(({ id, title }) => ({ id, title }))}
                    onMove={(id, direction) => moveItem.mutate({ id, direction })}
                    onAssign={(id, targetSectionId) => assign.mutate({ id, targetSectionId })}
                    busy={moveItem.isPending || assign.isPending}
                  />
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={() => setDraft((value) => (value === null ? 'open' : null))}>
          {draft === null ? '生成 Markdown 草稿' : '收起草稿'}
        </Button>
      </div>
      {draft !== null && (
        <pre
          data-new258-draft=""
          className="max-h-72 overflow-auto rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-2 text-xs text-[var(--lumi-text-secondary)]"
        >
          {draftQuery.isPending && '生成中…'}
          {draftQuery.data?.markdown ?? ''}
        </pre>
      )}
    </div>
  )
}
