/** NEW-227 章节级阅读计划 section —— 章节分配到几次阅读，完成按章节记账。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import {
  assignPlanSection,
  createSectionPlan,
  deleteSectionPlan,
  getSectionPlan,
  setPlanSectionDone,
  type SectionPlan,
} from './api'
import { Button } from '../ui/Button'
import { Chip, ErrorNote, ItemPicker, SectionShell, useTodayItems } from './parts'

/** 解析用户输入：每行一章；`标签@3` = 第 3 次阅读（可省略）。 */
function parseSections(raw: string): { label: string; sessionNo?: number }[] {
  return raw
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const match = /^(.*)@(\d{1,2})$/.exec(line)
      if (match) {
        return { label: match[1].trim(), sessionNo: Number(match[2]) }
      }
      return { label: line }
    })
}

export function PlanSection() {
  const qc = useQueryClient()
  const { items } = useTodayItems()
  const [ref, setRef] = useState('')
  const [raw, setRaw] = useState('')
  const [error, setError] = useState<unknown>(null)

  const planQuery = useQuery({
    queryKey: ['new2xx', 'plan', ref],
    queryFn: ({ signal }) => getSectionPlan(ref, signal),
    enabled: ref !== '',
    retry: false,
  })

  const invalidate = () => void qc.invalidateQueries({ queryKey: ['new2xx', 'plan'] })

  const createMutation = useMutation({
    mutationFn: () => createSectionPlan(ref, parseSections(raw)),
    onSuccess: () => {
      setRaw('')
      invalidate()
    },
    onError: setError,
  })
  const doneMutation = useMutation({
    mutationFn: ({ sectionId, done }: { sectionId: string; done: boolean }) =>
      setPlanSectionDone(sectionId, done),
    onSuccess: invalidate,
    onError: setError,
  })
  const assignMutation = useMutation({
    mutationFn: ({ sectionId, sessionNo }: { sectionId: string; sessionNo: number | null }) =>
      assignPlanSection(sectionId, sessionNo),
    onSuccess: invalidate,
    onError: setError,
  })
  const deleteMutation = useMutation({
    mutationFn: () => deleteSectionPlan(ref),
    onSuccess: invalidate,
    onError: setError,
  })

  const plan: SectionPlan | undefined = planQuery.error ? undefined : planQuery.data

  return (
    <SectionShell
      title="章节级阅读计划"
      hint="把长文的章节分到几次读完；每次结束勾掉完成的章节——进度按章节记账，不是文章百分比。"
    >
      <ErrorNote error={error} />
      <ItemPicker items={items} value={ref} onChange={setRef} label="长文" />

      {ref && !plan ? (
        <div className="flex flex-col gap-1.5 text-xs">
          <label className="flex flex-col gap-0.5 text-[var(--lumi-text-secondary)]">
            章节（每行一章；`标签@2` = 第 2 次阅读）
            <textarea
              value={raw}
              onChange={(event) => setRaw(event.target.value)}
              rows={4}
              placeholder={'引言@1\n方法@1\n结果@2\n讨论@2'}
              className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-separator)] bg-[var(--lumi-surface-elevated)] px-2 py-1 text-xs"
            />
          </label>
          <Button
            size="sm"
            disabled={createMutation.isPending || parseSections(raw).length === 0}
            onClick={() => createMutation.mutate()}
          >
            创建计划
          </Button>
        </div>
      ) : null}

      {plan ? (
        <div className="flex flex-col gap-1.5 text-xs">
          <p className="flex items-center gap-2 font-medium text-[var(--lumi-text-primary)]">
            进度：{plan.progress.doneSections}/{plan.progress.totalSections} 章
            <Chip tone="accent">还差 {plan.progress.pendingSections} 章</Chip>
          </p>
          <ul className="flex flex-col gap-1">
            {plan.sections.map((section) => (
              <li key={section.id} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={section.status === 'done'}
                  aria-label={`完成章节 ${section.label}`}
                  onChange={(event) =>
                    doneMutation.mutate({ sectionId: section.id, done: event.target.checked })
                  }
                />
                <span
                  className={
                    section.status === 'done'
                      ? 'text-[var(--lumi-text-tertiary)] line-through'
                      : 'text-[var(--lumi-text-primary)]'
                  }
                >
                  {section.label}
                </span>
                <select
                  aria-label={`分配 ${section.label} 到第几次阅读`}
                  value={section.sessionNo ?? ''}
                  onChange={(event) =>
                    assignMutation.mutate({
                      sectionId: section.id,
                      sessionNo: event.target.value ? Number(event.target.value) : null,
                    })
                  }
                  className="ml-auto min-h-7 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-separator)] bg-[var(--lumi-surface-elevated)] px-1 text-xs"
                >
                  <option value="">未分配</option>
                  {[1, 2, 3, 4, 5].map((sessionNo) => (
                    <option key={sessionNo} value={sessionNo}>
                      第 {sessionNo} 次
                    </option>
                  ))}
                </select>
              </li>
            ))}
          </ul>
          <Button size="sm" variant="ghost" onClick={() => deleteMutation.mutate()}>
            删除计划
          </Button>
        </div>
      ) : null}
    </SectionShell>
  )
}
