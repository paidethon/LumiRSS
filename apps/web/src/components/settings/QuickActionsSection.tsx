/** QuickActionsSection — N199 自定义多步快捷操作（设置 → 快捷键）。
 *
 * 创建具名 2-3 步序列（SAFE 动作白名单）+ 每个动作绑定一个快捷键
 * （复用 custom-shortcuts 的捕获/冲突/黑名单语义，绑定键为
 * `quick-action:<id>`）。执行在 Web 端逐步走各动作的 NORMAL 客户端
 * 函数（无旁路；写步骤先经确认），见 lib/quick-action-runner。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Play, Trash2 } from 'lucide-react'
import {
  createQuickAction,
  deleteQuickAction,
  listQuickActions,
} from '../../api/client'
import type { QuickActionStep } from '../../api/client'
import { assignShortcut, effectiveBinding, loadCustomShortcuts, resetShortcut, saveCustomShortcuts } from '../../lib/custom-shortcuts'
import { runQuickAction, type QuickActionExecutor, type QuickActionStepDef } from '../../lib/quick-action-runner'
import { useReaderUi, type AppSection } from '../../store/reader-ui'
import { Button } from '../../components/ui/Button'
import { EmptyState } from '../../components/ui/EmptyState'
import { Skeleton } from '../../components/ui/Skeleton'

/** 与 BFF quick_actions.SAFE_ACTIONS 同一词表的执行器（全部走既有
 * 客户端函数 = NORMAL 端点；没有任何新写路径）。 */
function buildExecutors(entryRef: string): Record<string, QuickActionExecutor> {
  return {
    add_to_queue: async (params) => {
      const ref = typeof params.entryRef === 'string' && params.entryRef !== '' ? params.entryRef : entryRef
      if (ref === '') throw new Error('当前没有打开的文章，无法加入队列。')
      // NORMAL 端点：POST /queue/today/items（与阅读队列面板同一函数）。
      const { addQueueItem } = await import('../../api/client')
      await addQueueItem({ itemRef: ref })
    },
    open_reader: async () => {
      // 打开阅读器 = 回到 home（时间线 + 阅读器上下文的既有导航动作）。
      useReaderUi.getState().selectSection('home')
    },
    open_section: async (params) => {
      const section = String(params.section ?? 'home')
      useReaderUi.getState().selectSection(section as AppSection)
    },
    open_search: async (params) => {
      useReaderUi.getState().selectSection('search')
      const query = typeof params.query === 'string' ? params.query : ''
      if (query !== '') {
        // 会话级搜索状态（SearchPage 同源）——与手动搜索同一入口。
        const { useSearchState } = await import('../../store/search-state')
        useSearchState.getState().setQ(query)
        useSearchState.getState().setSubmitted(query)
      }
    },
  }
}

const SAFE_STEP_OPTIONS: { action: string; label: string; params: Record<string, unknown>; write?: boolean }[] = [
  { action: 'add_to_queue', label: '当前文章加入阅读队列（写）', params: {}, write: true },
  { action: 'open_reader', label: '打开阅读器', params: {} },
  { action: 'open_section', label: '跳到书签页', params: { section: 'bookmarks' } },
  { action: 'open_section', label: '跳到工作区', params: { section: 'workspaces' } },
  { action: 'open_search', label: '打开搜索页', params: { query: '' } },
]

export function QuickActionsSection() {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [stepSelections, setStepSelections] = useState<number[]>([0, 1])
  const [bindingDraft, setBindingDraft] = useState('')
  const [runNotice, setRunNotice] = useState<string | null>(null)
  const [entryRef, setEntryRef] = useState('')

  const listQuery = useQuery({
    queryKey: ['quick-actions'],
    queryFn: ({ signal }) => listQuickActions(signal),
    retry: false,
  })
  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['quick-actions'] })
  }
  const createMutation = useMutation({
    mutationFn: () =>
      createQuickAction({
        name: name.trim(),
        steps: stepSelections.map(
          (i): QuickActionStep => {
            const option = SAFE_STEP_OPTIONS[i]
            return { action: option.action, params: option.params }
          },
        ),
      }),
    onSuccess: async () => {
      setName('')
      setStepSelections([0, 1])
      await invalidate()
    },
  })
  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteQuickAction(id),
    onSuccess: async () => {
      await invalidate()
    },
  })

  const run = async (action: { id: string; name: string; steps: QuickActionStep[] }) => {
    setRunNotice(null)
    const executors = buildExecutors(entryRef)
    const steps: QuickActionStepDef[] = action.steps.map((step) => ({
      ...step,
      // add_to_queue 是写动作：与手动加入同一条确认路径。
      write: step.action === 'add_to_queue',
    }))
    const result = await runQuickAction(steps, executors, {
      confirm: async (step) =>
        window.confirm(`步骤「${step.action}」会写入阅读队列，确认执行？`),
    })
    if (result.status === 'completed') {
      setRunNotice(`「${action.name}」已完成 ${result.steps.length} 步。`)
    } else if (result.status === 'cancelled') {
      setRunNotice(`「${action.name}」在第 ${result.steps.length} 步被取消。`)
    } else {
      setRunNotice(
        `「${action.name}」在第 ${(result.failedIndex ?? 0) + 1} 步停止：${
          result.error instanceof Error ? result.error.message : '执行失败'
        }`,
      )
    }
  }

  const bindShortcut = (actionId: string) => {
    const custom = loadCustomShortcuts()
    const result = assignShortcut(custom, `quick-action:${actionId}`, bindingDraft)
    if (result.error === 'reserved') {
      setRunNotice('该组合为浏览器保留键，无法分配。')
      return
    }
    if (result.error === 'conflict') {
      setRunNotice('该组合已被其他动作占用（覆盖需先清除旧绑定）。')
      return
    }
    saveCustomShortcuts(result.custom)
    setBindingDraft('')
    setRunNotice('已绑定快捷键。')
  }

  const items = listQuery.data?.items ?? []
  const customShortcuts = loadCustomShortcuts()

  return (
    <div className="flex flex-col gap-3" data-testid="quick-actions-section">
      <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        把 2-3 个安全动作串成具名序列。每一步都走它原本的普通接口与确认
        路径（无旁路）；任一步失败即停。可给每个动作绑定一个快捷键。
      </p>

      <div className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3">
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="操作名称（如：加入队列并打开阅读器）"
            aria-label="快捷操作名称"
            className="min-w-40 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 text-xs"
          />
          <input
            type="text"
            value={entryRef}
            onChange={(e) => setEntryRef(e.target.value)}
            placeholder="当前文章 entryRef（加入队列用）"
            aria-label="队列目标文章 entryRef"
            className="min-w-40 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 text-xs"
          />
        </div>
        {stepSelections.map((selected, index) => (
          <label key={index} className="flex items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
            第 {index + 1} 步
            <select
              aria-label={`第 ${index + 1} 步动作`}
              value={selected}
              onChange={(e) =>
                setStepSelections((prev) => {
                  const next = [...prev]
                  next[index] = Number(e.target.value)
                  return next
                })
              }
              className="flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
            >
              {SAFE_STEP_OPTIONS.map((option, i) => (
                <option key={`${option.action}-${i}`} value={i}>{option.label}</option>
              ))}
            </select>
          </label>
        ))}
        {stepSelections.length < 3 && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setStepSelections((prev) => [...prev, 1])}
          >
            + 第三步
          </Button>
        )}
        <div>
          <Button
            size="sm"
            variant="primary"
            disabled={name.trim() === '' || createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            创建快捷操作
          </Button>
        </div>
        {createMutation.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {createMutation.error instanceof Error ? createMutation.error.message : '创建失败'}
          </p>
        )}
      </div>

      {listQuery.isPending && <Skeleton className="h-12 w-full" />}
      {listQuery.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-text-tertiary)]">
          快捷操作列表不可用（服务端版本较旧时不影响其他功能）。
        </p>
      )}
      {listQuery.isSuccess && items.length === 0 && (
        <EmptyState title="还没有快捷操作" description="上方创建一个 2-3 步的序列。" />
      )}
      <ul className="flex flex-col gap-1.5">
        {items.map((action) => {
          const binding = effectiveBinding(`quick-action:${action.id}`, {}, customShortcuts)
          return (
            <li
              key={action.id}
              className="flex flex-wrap items-center gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-2.5"
            >
              <div className="min-w-0 flex-1">
                <p className="text-sm text-[var(--lumi-text-primary)]">{action.name}</p>
                <p className="text-xs text-[var(--lumi-text-tertiary)]">
                  {action.steps.map((s) => s.action).join(' → ')}
                </p>
              </div>
              <div className="flex items-center gap-1">
                <input
                  type="text"
                  value={binding !== '' ? binding : bindingDraft}
                  readOnly={binding !== ''}
                  onChange={(e) => setBindingDraft(e.target.value)}
                  placeholder="快捷键（如 mod+j）"
                  aria-label={`为 ${action.name} 绑定快捷键`}
                  className="w-32 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
                />
                <Button size="sm" variant="ghost" onClick={() => bindShortcut(action.id)}>
                  绑定
                </Button>
                {binding !== '' && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      saveCustomShortcuts(resetShortcut(loadCustomShortcuts(), `quick-action:${action.id}`))
                      setRunNotice('已清除快捷键。')
                    }}
                  >
                    清除
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => void run(action)}
                >
                  <Play aria-hidden className="size-3.5" /> 运行
                </Button>
                <button
                  type="button"
                  aria-label={`删除 ${action.name}`}
                  onClick={() => deleteMutation.mutate(action.id)}
                  className="text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-danger)]"
                >
                  <Trash2 aria-hidden className="size-3.5" />
                </button>
              </div>
            </li>
          )
        })}
      </ul>
      {runNotice !== null && (
        <p role="status" data-testid="quick-action-notice" className="text-xs text-[var(--lumi-text-secondary)]">
          {runNotice}
        </p>
      )}
    </div>
  )
}
