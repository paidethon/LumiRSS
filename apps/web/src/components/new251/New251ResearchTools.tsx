/** NEW-251..260 研究项目工具组（单一挂载点）— 问题拆分(251)、假设登记册(252)、
 * 反例收集(253)、研究术语表(254)、事件时间线(255)、决策记录(256)、资料缺口(257)、
 * 大纲编排(258)、结论变更记录(259)、分享脱敏预览(260)。
 *
 * 情境展开（MASTER §6：高级工具按情境展开，不常驻渲染）：折叠态不发起
 * 任何查询——工作区页既有测试与真实首屏都不为这组低频研究工具付网络/
 * 渲染成本；展开后才挂载项目选择器与子面板。项目是本组共用主线
 * （research_projects，per-user 库天然隔离），展开后先选/建项目，
 * 未选项目时同样零子面板查询。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  createResearchProject,
  deleteResearchProject,
  listResearchProjects,
} from '../../api/new251'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { ConclusionHistoryPanel } from './ConclusionHistoryPanel'
import { CounterexamplesPanel } from './CounterexamplesPanel'
import { DecisionsPanel } from './DecisionsPanel'
import { GapsPanel } from './GapsPanel'
import { HypothesesPanel } from './HypothesesPanel'
import { OutlinePanel } from './OutlinePanel'
import { ResearchGlossaryPanel } from './ResearchGlossaryPanel'
import { ResearchQuestionsPanel } from './ResearchQuestionsPanel'
import { SharePreviewPanel } from './SharePreviewPanel'
import { ErrorLine, NoticeLine, SelectField, TextField } from './parts'
import { TimelinePanel } from './TimelinePanel'

export function New251ResearchTools() {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [projectId, setProjectId] = useState<string>('')
  const [title, setTitle] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  // 折叠态零查询：enabled 关死，首屏/工作区页测试都不付成本。
  const projects = useQuery({
    queryKey: ['new251-projects'],
    queryFn: ({ signal }) => listResearchProjects(signal),
    enabled: open,
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['new251-projects'] })

  const createMutation = useMutation({
    mutationFn: () => createResearchProject(title),
    onSuccess: async (created) => {
      setTitle('')
      setProjectId(created.id)
      setNotice('研究项目已创建（只是本人库里的分组锚点，无任何共享面）。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '创建失败'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteResearchProject(id),
    onSuccess: async (_data, deletedId) => {
      setConfirmDeleteId(null)
      if (projectId === deletedId) setProjectId('')
      setNotice('研究项目已删除（连带其问题/假设/台账等本组数据）。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '删除失败'),
  })

  const items = projects.data?.items ?? []
  const activeProject = items.find((item) => item.id === projectId) ?? null
  return (
    <section aria-label="研究项目工具（NEW-251..260）" className="mt-8 flex flex-col gap-3">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="self-start text-sm text-[var(--lumi-accent)] underline underline-offset-2"
      >
        {open ? '收起研究项目工具' : '研究项目工具（问题拆分 / 假设 / 反例 / 术语 / 时间线 / 决策 / 缺口 / 大纲 / 结论史 / 分享预览）'}
      </button>
      {open && (
        <div className="flex flex-col gap-3" data-new251-research-tools="">
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-48 flex-1">
              <TextField label="新建研究项目" value={title} onChange={setTitle} placeholder="这个专题要研究什么" />
            </div>
            <Button size="sm" onClick={() => createMutation.mutate()} disabled={createMutation.isPending}>
              创建项目
            </Button>
          </div>
          <ErrorLine error={projects.error} />
          <NoticeLine notice={notice} />
          {projects.data !== undefined && items.length === 0 && (
            <EmptyState
              title="尚无研究项目"
              description="先创建一个项目；项目只是分组锚点，不预置任何示例内容。"
            />
          )}
          {items.length > 0 && (
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-48 flex-1">
                <SelectField
                  label="当前研究项目"
                  value={projectId}
                  onChange={setProjectId}
                  options={[
                    { value: '', label: '— 选择项目 —' },
                    ...items.map((item) => ({ value: item.id, label: item.title })),
                  ]}
                />
              </div>
              {activeProject !== null && (
                confirmDeleteId === activeProject.id ? (
                  <>
                    <Button
                      size="sm"
                      onClick={() => deleteMutation.mutate(activeProject.id)}
                      disabled={deleteMutation.isPending}
                    >
                      确认删除
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirmDeleteId(null)}>
                      取消
                    </Button>
                  </>
                ) : (
                  <Button size="sm" variant="ghost" onClick={() => setConfirmDeleteId(activeProject.id)}>
                    删除当前项目
                  </Button>
                )
              )}
            </div>
          )}
          {projectId !== '' && activeProject !== null && (
            <>
              <ResearchQuestionsPanel projectId={projectId} />
              <HypothesesPanel projectId={projectId} />
              <CounterexamplesPanel projectId={projectId} />
              <ResearchGlossaryPanel projectId={projectId} />
              <TimelinePanel projectId={projectId} />
              <DecisionsPanel projectId={projectId} />
              <GapsPanel projectId={projectId} />
              <OutlinePanel projectId={projectId} />
              <ConclusionHistoryPanel projectId={projectId} />
              <SharePreviewPanel projectId={projectId} />
            </>
          )}
        </div>
      )}
    </section>
  )
}
