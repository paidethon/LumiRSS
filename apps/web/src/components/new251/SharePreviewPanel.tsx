/** NEW-260 研究分享脱敏预览 — 共享前逐项盘点私人笔记、成员名字与附件。
 *
 * 盘点只读（GET /share-preview）：私人笔记逐项勾选「可带出」，成员名
 * 出现位置逐项勾选「匿名化」，附件区诚实返回空表 + 说明（研究组各表
 * 不存附件）。确认后存「可带出清单」快照（append-only）——这只是核对
 * 记录，不产出任何真实分享包（诚实边界：核对工具，不是发布管道）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  confirmShare,
  getSharePreview,
  listShareConfirmations,
} from '../../api/new251'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { ErrorLine, NoticeLine, ToolSection } from './parts'

export function SharePreviewPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const [includeIds, setIncludeIds] = useState<Set<string>>(new Set())
  const [anonymizeNames, setAnonymizeNames] = useState<Set<string>>(new Set())
  const [notice, setNotice] = useState<string | null>(null)

  const preview = useQuery({
    queryKey: ['new260-share-preview', projectId],
    queryFn: ({ signal }) => getSharePreview(projectId, signal),
  })
  const confirmations = useQuery({
    queryKey: ['new260-share-confirmations', projectId],
    queryFn: ({ signal }) => listShareConfirmations(projectId, signal),
  })

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['new260-share-confirmations', projectId] })
  }

  const confirmMutation = useMutation({
    mutationFn: () =>
      confirmShare(projectId, {
        includePrivateNoteIds: [...includeIds],
        anonymizeMemberUsernames: [...anonymizeNames],
      }),
    onSuccess: async (result) => {
      setNotice(
        `已存确认快照（可带出私人笔记 ${result.manifest.includePrivateNoteIds.length} 条；` +
          `匿名化成员名 ${result.manifest.anonymizeMemberUsernames.length} 个）。快照只是核对记录，不产出真实分享包。`,
      )
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '确认失败'),
  })

  const toggle = (set: Set<string>, value: string): Set<string> => {
    const next = new Set(set)
    if (next.has(value)) next.delete(value)
    else next.add(value)
    return next
  }

  const notes = preview.data?.privateNotes ?? []
  const names = preview.data?.memberNames ?? []
  return (
    <div data-new260-share-preview="" className="flex flex-col gap-3">
      <ErrorLine error={preview.error ?? confirmations.error} />
      {preview.data !== undefined && notes.length === 0 && names.length === 0 && (
        <EmptyState
          title="没有发现需要脱敏的内容"
          description="项目自由文本里没有私人笔记，也没有成员名字出现。"
        />
      )}
      <ToolSection title="私人笔记" description="逐项勾选允许带出的笔记；不勾 = 留在本地。">
        {notes.map((item) => (
          <label
            key={item.id}
            data-new260-note-item={item.id}
            className="flex items-start gap-2 text-xs text-[var(--lumi-text-secondary)]"
          >
            <input
              type="checkbox"
              aria-label={`允许带出私人笔记（${item.table}.${item.field}）`}
              className="mt-0.5"
              checked={includeIds.has(item.id)}
              onChange={() => setIncludeIds((prev) => toggle(prev, item.id))}
            />
            <span>
              [{item.table}.{item.field}] {item.excerpt}
            </span>
          </label>
        ))}
        {preview.data !== undefined && notes.length === 0 && (
          <p className="text-xs text-[var(--lumi-text-tertiary)]">无私人笔记。</p>
        )}
      </ToolSection>
      <ToolSection title="成员名字" description="控制库成员名单在项目文本中的出现位置；勾选 = 匿名化。">
        {names.map((hit) => (
          <label
            key={hit.username}
            data-new260-name-item={hit.username}
            className="flex items-start gap-2 text-xs text-[var(--lumi-text-secondary)]"
          >
            <input
              type="checkbox"
              aria-label={`匿名化成员名 ${hit.username}`}
              className="mt-0.5"
              checked={anonymizeNames.has(hit.username)}
              onChange={() => setAnonymizeNames((prev) => toggle(prev, hit.username))}
            />
            <span>
              {hit.username}：出现 {hit.occurrences.length} 处
            </span>
          </label>
        ))}
        {preview.data !== undefined && names.length === 0 && (
          <p className="text-xs text-[var(--lumi-text-tertiary)]">未发现成员名字。</p>
        )}
      </ToolSection>
      <ToolSection title="附件" description={preview.data?.attachmentsNote ?? ''}>
        <p className="text-xs text-[var(--lumi-text-tertiary)]">
          研究组各表不存附件（附件属于 library 域）——本区诚实为空，不伪造条目。
        </p>
      </ToolSection>
      <div>
        <Button
          size="sm"
          onClick={() => confirmMutation.mutate()}
          disabled={confirmMutation.isPending || preview.isPending}
        >
          存确认快照
        </Button>
      </div>
      <NoticeLine notice={notice} />
      {(confirmations.data?.items ?? []).length > 0 && (
        <ol className="flex flex-col gap-1">
          {confirmations.data?.items.map((confirmation) => (
            <li
              key={confirmation.id}
              data-new260-confirmation={confirmation.id}
              className="text-xs text-[var(--lumi-text-tertiary)]"
            >
              {confirmation.createdAt.slice(0, 19).replace('T', ' ')} · 笔记{' '}
              {confirmation.manifest.includePrivateNoteIds.length} 条 · 匿名{' '}
              {confirmation.manifest.anonymizeMemberUsernames.length} 个
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
