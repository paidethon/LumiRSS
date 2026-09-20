/** AiTaskCenterPanel — F063 AI 任务中心（设置 → AI 区）。
 *
 * 最近 AI 任务列表（时间/类型/状态/耗时/错误类型）+ 失败的
 * summary 任务可重试（服务端重建输入；原记录不变）。
 * Agent 会话不在此重试——沿用既有线程 cancel 入口（面板顶部说明）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, ListChecks, RefreshCw } from 'lucide-react'
import { listAiTasks, retryAiTask, type AiTaskRecord } from '../../api/client'
import { formatListTime } from '../../lib/date-format'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/Skeleton'

const KIND_LABELS: Record<string, string> = {
  summary: '摘要',
  translation: '翻译',
  conversation: '对话',
  quiz: '自测',
  cards: '知识卡片',
  compare: '观点对照',
  ask_batch: '多篇问答',
}

const ERROR_LABELS: Record<string, string> = {
  rate_limited: '上游限流',
  timeout: '上游超时',
  upstream: '上游错误',
  invalid_response: '无效响应',
  ai_not_configured: 'AI 未配置',
  auth_error: '鉴权失败',
  model_error: '模型不可用',
}

function errorLabel(t: string | null): string {
  if (t === null) return ''
  return ERROR_LABELS[t] ?? t
}

export function AiTaskCenterPanel() {
  const queryClient = useQueryClient()
  const tasksQuery = useQuery({
    queryKey: ['ai-tasks'],
    queryFn: () => listAiTasks(50),
    staleTime: 10_000,
  })
  const retry = useMutation({
    mutationFn: (id: string) => retryAiTask(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['ai-tasks'] })
    },
  })

  const items = tasksQuery.data?.items ?? []
  const failed = items.filter((t) => t.status === 'failed')

  return (
    <section
      data-lumi-ai-task-center=""
      aria-label="AI 任务中心"
      className="mt-6 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-4"
    >
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-[var(--lumi-text-primary)]">
        <ListChecks aria-hidden className="size-4" />
        任务中心
      </h3>
      <p className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">
        最近 50 次 AI 生成任务（摘要/翻译/对话等）。失败的摘要任务可在此重试；
        Agent 会话请沿用会话内既有的取消入口。
      </p>

      {tasksQuery.isPending && (
        <div className="mt-3 flex flex-col gap-2" aria-label="任务加载中">
          <Skeleton className="h-5 w-full" />
          <Skeleton className="h-5 w-4/5" />
          <Skeleton className="h-5 w-3/5" />
        </div>
      )}
      {tasksQuery.isError && (
        <p role="alert" className="mt-3 flex items-center gap-1.5 text-xs text-[var(--lumi-danger)]">
          <AlertCircle aria-hidden className="size-3.5" />
          任务列表加载失败。
          <Button size="sm" variant="ghost" onClick={() => tasksQuery.refetch()}>
            重试
          </Button>
        </p>
      )}
      {!tasksQuery.isPending && !tasksQuery.isError && items.length === 0 && (
        <p className="mt-3 text-xs text-[var(--lumi-text-tertiary)]">
          还没有 AI 任务记录。生成摘要、翻译或对话后会在这里显示。
        </p>
      )}

      {items.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1.5">
          {items.map((task: AiTaskRecord) => (
            <li
              key={task.id}
              className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1.5 text-xs"
            >
              <span className="text-[var(--lumi-text-tertiary)]">
                {formatListTime(task.createdAt, 'absolute')}
              </span>
              <span className="font-medium text-[var(--lumi-text-primary)]">
                {KIND_LABELS[task.kind] ?? task.kind}
              </span>
              <span
                className={
                  task.status === 'done'
                    ? 'rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[var(--lumi-text-secondary)]'
                    : 'rounded-[var(--lumi-radius-full)] bg-[var(--lumi-danger-soft, var(--lumi-surface-selected))] px-1.5 py-0.5 text-[var(--lumi-danger)]'
                }
              >
                {task.status === 'done' ? '完成' : '失败'}
              </span>
              <span className="text-[var(--lumi-text-tertiary)]">{task.durationMs} ms</span>
              {task.status === 'failed' && task.errorType !== null && (
                <span className="text-[var(--lumi-danger)]">
                  {errorLabel(task.errorType)}
                </span>
              )}
              {task.status === 'failed' && task.kind === 'summary' && task.entryRef !== null && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={retry.isPending}
                  onClick={() => retry.mutate(task.id)}
                >
                  <RefreshCw aria-hidden className="size-3" />
                  重试
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {retry.isError && (
        <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">
          重试失败：该类任务可能无法从任务中心直接重试。
        </p>
      )}
      {failed.length === 0 && items.length > 0 && (
        <p className="mt-2 text-xs text-[var(--lumi-text-tertiary)]">近期没有失败任务。</p>
      )}
    </section>
  )
}
