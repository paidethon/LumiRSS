/** ModuleCleanupPanel — NEW-400 个人功能使用清理。
 *
 * 列出用户主动启用但可能已不需要的高级模块（计数实时来自各功能自己的
 * 表）；由本人显式关闭并选择保留数据（keep）或一并清除（delete）。
 * 绝不根据行为推断自动关闭——本面板没有任何自动路径。
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { closeModule, fetchModuleCleanup, type CleanupModule } from '../../api/new391'
import { Button } from '../ui/Button'
import { NoteText, StatusLine } from './parts'

function ModuleRow({ module }: { module: CleanupModule }) {
  const [confirmOpen, setConfirmOpen] = useState(false)
  const queryClient = useQueryClient()
  const close = useMutation({
    mutationFn: (retention: 'keep' | 'delete') => closeModule(module.key, retention),
    onSuccess: () => {
      setConfirmOpen(false)
      void queryClient.invalidateQueries({ queryKey: ['new391', 'cleanup'] })
    },
  })
  return (
    <li
      data-n391-cleanup-module={module.key}
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-medium text-[var(--lumi-text-primary)]">
          {module.label}
        </span>
        <span data-n391-module-count={module.key} className="text-xs text-[var(--lumi-text-tertiary)]">
          启用中 {module.enabledCount} 项
        </span>
      </div>
      <NoteText>{module.description}</NoteText>
      {module.closure ? (
        <StatusLine tone="info">
          已由本人关闭（{module.closure.retention === 'keep' ? '保留数据' : '删除数据'}）：{module.closure.detail}
        </StatusLine>
      ) : confirmOpen ? (
        <div className="flex flex-col gap-1">
          <NoteText>选择数据去留：保留数据可随时回来重新启用；删除则一并清除。</NoteText>
          <span className="flex gap-1">
            <Button size="sm" loading={close.isPending} onClick={() => close.mutate('keep')}>
              关闭并保留数据
            </Button>
            <Button size="sm" variant="danger" loading={close.isPending} onClick={() => close.mutate('delete')}>
              关闭并删除数据
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirmOpen(false)}>
              取消
            </Button>
          </span>
        </div>
      ) : (
        <Button
          className="self-start"
          size="sm"
          variant="ghost"
          onClick={() => setConfirmOpen(true)}
        >
          我不再需要这个功能
        </Button>
      )}
    </li>
  )
}

export function ModuleCleanupPanel() {
  const cleanup = useQuery({
    queryKey: ['new391', 'cleanup'],
    queryFn: fetchModuleCleanup,
  })
  if (cleanup.isLoading) {
    return (
      <div data-n391-panel="module-cleanup">
        <StatusLine tone="info">正在加载清理清单…</StatusLine>
      </div>
    )
  }
  if (cleanup.isError) {
    return (
      <div data-n391-panel="module-cleanup">
        <StatusLine tone="error">清理清单加载失败。</StatusLine>
      </div>
    )
  }
  return (
    <div data-n391-panel="module-cleanup" className="flex flex-col gap-3">
      <NoteText>{cleanup.data?.note}</NoteText>
      <ul className="flex flex-col gap-2">
        {cleanup.data?.modules.map((module) => (
          <ModuleRow key={module.key} module={module} />
        ))}
      </ul>
    </div>
  )
}
