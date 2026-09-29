/** NEW-241 文章更新差异阅读 — 保存版本 / 版本列表 / 阅读所选版本 / 段落级差异。
 *
 * 版本是用户显式保存的（含粘贴正文）；差异只读：增加 / 删除 / 修改
 * 段落计数 + 逐块展示。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  diffArticleVersions,
  listArticleVersions,
  readArticleVersion,
  saveArticleVersion,
  type ParagraphDiff,
} from '../../api/new241'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'

const BLOCK_LABELS: Record<string, string> = {
  unchanged: '不变',
  added: '增加',
  removed: '删除',
  modified: '修改',
}

export function ArticleVersionsPanel({ entryRef }: { entryRef: string }) {
  const queryClient = useQueryClient()
  const [label, setLabel] = useState('')
  const [pasted, setPasted] = useState('')
  const [fromId, setFromId] = useState('')
  const [toId, setToId] = useState('')
  const [diff, setDiff] = useState<ParagraphDiff | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const versions = useQuery({
    queryKey: ['new241-article-versions', entryRef],
    queryFn: ({ signal }) => listArticleVersions(entryRef, signal),
  })
  const readQuery = useQuery({
    queryKey: ['new241-article-version-read', entryRef, toId],
    queryFn: ({ signal }) => readArticleVersion(entryRef, toId, signal),
    enabled: toId !== '',
  })

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['new241-article-versions', entryRef] })
  }

  const saveMutation = useMutation({
    mutationFn: () => saveArticleVersion(entryRef, label, pasted),
    onSuccess: async () => {
      setNotice('已保存为新版本。')
      setLabel('')
      setPasted('')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '保存失败'),
  })
  const diffMutation = useMutation({
    mutationFn: () => diffArticleVersions(entryRef, fromId, toId),
    onSuccess: (result) => setDiff(result),
    onError: (error) => setNotice(error instanceof Error ? error.message : '差异计算失败'),
  })

  const items = versions.data?.items ?? []

  return (
    <section
      aria-label="文章更新差异阅读（NEW-241）"
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
    >
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">文章更新差异阅读</h3>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">NEW-241</span>
      </div>

      {versions.isPending && <Skeleton className="h-16 w-full" />}
      {versions.isError && (
        <div role="alert" className="text-xs text-[var(--lumi-text-secondary)]">
          版本加载失败。{versions.error instanceof Error ? versions.error.message : ''}
        </div>
      )}
      {!versions.isPending && items.length === 0 && !versions.isError && (
        <EmptyState title="还没有保存过版本" description="粘贴正文并命名保存后，可在两个版本间对比段落增删改。" />
      )}

      {items.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
          <label>
            基准版本
            <select
              aria-label="选择基准版本"
              value={fromId}
              onChange={(event) => setFromId(event.target.value)}
              className="ml-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1"
            >
              <option value="">选择…</option>
              {items.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            对比版本
            <select
              aria-label="选择对比版本"
              value={toId}
              onChange={(event) => {
                setToId(event.target.value)
                setDiff(null)
              }}
              className="ml-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1"
            >
              <option value="">选择…</option>
              {items.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <Button
            size="sm"
            variant="secondary"
            disabled={fromId === '' || toId === '' || fromId === toId || diffMutation.isPending}
            onClick={() => diffMutation.mutate()}
          >
            对比段落差异
          </Button>
        </div>
      )}

      {diff !== null && (
        <div className="flex flex-col gap-1" aria-label="段落差异">
          <p className="text-xs text-[var(--lumi-text-secondary)]">
            {diff.identical ? '两个版本内容一致。' : `增加 ${diff.added} 段 / 删除 ${diff.removed} 段 / 修改 ${diff.modified} 段`}
          </p>
          {!diff.identical &&
            diff.blocks.map((block, index) => (
              <div
                key={index}
                className={
                  block.type === 'added'
                    ? 'rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-hover)] p-2 text-xs'
                    : 'p-2 text-xs text-[var(--lumi-text-secondary)]'
                }
              >
                <span className="mr-2 text-[var(--lumi-text-tertiary)]">
                  {BLOCK_LABELS[block.type] ?? block.type}
                </span>
                {block.type === 'modified' ? `${block.oldText} → ${block.newText}` : block.text}
              </div>
            ))}
        </div>
      )}

      {/* 阅读所选版本全文 */}
      {toId !== '' && readQuery.data && (
        <details className="text-xs text-[var(--lumi-text-secondary)]">
          <summary className="cursor-pointer">阅读「{items.find((i) => i.id === toId)?.label ?? ''}」全文</summary>
          <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-hover)] p-2">
            {readQuery.data.contentText}
          </pre>
        </details>
      )}

      <div className="flex flex-col gap-1">
        <input
          aria-label="新版本标签"
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          placeholder="例如：保存时的版本"
          className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
        />
        <textarea
          aria-label="粘贴当前正文以保存为版本"
          value={pasted}
          onChange={(event) => setPasted(event.target.value)}
          placeholder="粘贴当前正文文本（空行分段）…"
          rows={3}
          className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
        />
        <Button
          size="sm"
          variant="secondary"
          className="self-start"
          disabled={label.trim() === '' || pasted.trim() === '' || saveMutation.isPending}
          onClick={() => saveMutation.mutate()}
        >
          保存为版本
        </Button>
      </div>

      {notice !== null && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
          {notice}
        </p>
      )}
    </section>
  )
}
