/** SaveSearchDialog — N144 按检索范围收藏（保存搜索视图对话框）。
 *
 * 在既有「查询+视图」意图之外，暴露检索范围：
 * - 工作区（可选；仅列真实存在的工作区，服务端会校验）；
 * - 内容类型（可选多选；RSS 腿 + 库腿各 kind）。
 * 重新打开视图时范围随视图还原；保存后工作区被删除 → 列表诚实标注
 * scopeBroken（「已失效」横幅 + 解除关联，由视图 chips 行负责）。
 */

import { useMemo, useState } from 'react'
import { useWorkspaces, useCreateSavedSearchViewMutation } from '../api/queries'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { cx } from './ui/cx'

/** 与 BFF saved_search_store._ALLOWED_CONTENT_TYPES 同一白名单。 */
const CONTENT_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: 'rss', label: 'RSS 文章' },
  { value: 'bookmark', label: '书签' },
  { value: 'clip', label: '剪藏' },
  { value: 'obsidian_note', label: '笔记' },
  { value: 'snapshot', label: '快照' },
  { value: 'api_item', label: '收件' },
]

export function SaveSearchDialog({
  open,
  defaultName,
  query,
  view,
  categoryKey,
  onClose,
}: {
  open: boolean
  defaultName: string
  query: string
  view: string
  categoryKey: string
  onClose: () => void
}) {
  const [name, setName] = useState(defaultName)
  const [workspaceId, setWorkspaceId] = useState<string>('')
  const [contentTypes, setContentTypes] = useState<string[]>([])
  const workspaces = useWorkspaces()
  const workspaceList = useMemo(
    () =>
      Array.isArray(workspaces.data)
        ? workspaces.data
        : (workspaces.data?.items ?? []),
    [workspaces.data],
  )
  const create = useCreateSavedSearchViewMutation()

  if (!open) return null
  const trimmedName = name.trim()
  const canSubmit = trimmedName !== '' && query.trim() !== '' && !create.isPending

  const toggleType = (value: string) => {
    setContentTypes((prev) =>
      prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value],
    )
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title="保存此搜索"
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={onClose} disabled={create.isPending}>
            取消
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={!canSubmit}
            onClick={() => {
              if (!canSubmit) return
              create.mutate(
                {
                  name: trimmedName,
                  query: query.trim(),
                  view,
                  categoryKey,
                  workspaceId: workspaceId === '' ? null : workspaceId,
                  contentTypes: contentTypes.length > 0 ? contentTypes : null,
                },
                { onSuccess: onClose },
              )
            }}
          >
            {create.isPending ? '保存中…' : '保存'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">名称</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={60}
            autoFocus
            aria-label="视图名称"
            className="w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2 text-sm text-[var(--lumi-text-primary)] focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">
            工作区范围（可选）
          </span>
          <select
            value={workspaceId}
            onChange={(e) => setWorkspaceId(e.target.value)}
            aria-label="工作区范围"
            className="min-h-9 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-sm text-[var(--lumi-text-primary)]"
          >
            <option value="">不限工作区</option>
            {workspaceList
              .filter((w) => !w.archived)
              .map((workspace) => (
                <option key={workspace.id} value={workspace.id}>
                  {workspace.name}
                </option>
              ))}
          </select>
          {workspaces.isError && (
            <span role="alert" className="text-[11px] text-[var(--lumi-danger)]">
              工作区列表加载失败，可先不选。
            </span>
          )}
        </label>
        <div className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">
            内容类型范围（可选多选）
          </span>
          <div role="group" aria-label="内容类型范围" className="flex flex-wrap gap-x-3 gap-y-1.5">
            {CONTENT_TYPE_OPTIONS.map((option) => (
              <label key={option.value} className="flex items-center gap-1 text-xs text-[var(--lumi-text-secondary)]">
                <input
                  type="checkbox"
                  checked={contentTypes.includes(option.value)}
                  onChange={() => toggleType(option.value)}
                  className="size-3.5 accent-[var(--lumi-accent)]"
                />
                {option.label}
              </label>
            ))}
          </div>
          <span
            data-testid="scope-hint"
            className={cx(
              'text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]',
            )}
          >
            范围会随视图一起保存并在重新打开时还原；保存后工作区若被删除，视图会标注「已失效」，可随时解除关联。
          </span>
        </div>
        {create.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {create.error instanceof Error ? create.error.message : '保存失败，请稍后重试。'}
          </p>
        )}
      </div>
    </Dialog>
  )
}
