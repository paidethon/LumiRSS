/** New216CollectionOpsPanel — NEW-216..218 集合整理工作台（WorkspacesPage 挂载）。
 *
 * 三个分区：快照差异（capture/list/diff/按选恢复）/ 排序配方（创建 +
 * 预览 + 应用，explain 随配方展示）/ 引用关系检查（失效清单 + 重新关联
 * 或保留失效标记）。全部只打 NEW 组端点，三态齐全。
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderTree } from 'lucide-react'
import * as api from './api'
import { ApiError } from './api'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Select } from '../ui/Select'
import { Skeleton } from '../ui/Skeleton'

type Section = 'snapshots' | 'recipes' | 'references'

const SECTIONS: { key: Section; label: string }[] = [
  { key: 'snapshots', label: '快照差异' },
  { key: 'recipes', label: '排序配方' },
  { key: 'references', label: '引用检查' },
]

function errText(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return String(error)
}

function useWorkspaces() {
  return useQuery({ queryKey: ['new216-workspaces'], queryFn: api.listWorkspaces })
}

function WorkspacePicker({
  workspaceId,
  onChange,
}: {
  workspaceId: string
  onChange: (id: string) => void
}) {
  const workspaces = useWorkspaces()
  if (workspaces.isLoading) return <Skeleton className="h-8" />
  return (
    <Select
      aria-label="选择集合"
      value={workspaceId}
      onChange={(event) => onChange(event.target.value)}
      options={[
        { value: '', label: '选择集合…' },
        ...(workspaces.data?.items ?? []).map((w) => ({ value: w.id, label: w.name })),
      ]}
    />
  )
}

// ---- NEW-216 快照差异 -------------------------------------------------------

function SnapshotsSection() {
  const qc = useQueryClient()
  const [workspaceId, setWorkspaceId] = useState('')
  const snapshots = useQuery({
    queryKey: ['new216-snapshots', workspaceId],
    queryFn: () => api.listMemberSnapshots(workspaceId),
    enabled: workspaceId !== '',
  })
  const [name, setName] = useState('')
  const [aId, setAId] = useState('')
  const [bId, setBId] = useState('')
  const [diff, setDiff] = useState<api.SnapshotDiff | null>(null)
  const [picked, setPicked] = useState<string[]>([])

  const captureMutation = useMutation({
    mutationFn: () => api.captureMemberSnapshot(workspaceId, name),
    onSuccess: () => {
      setName('')
      void qc.invalidateQueries({ queryKey: ['new216-snapshots', workspaceId] })
    },
  })
  const diffMutation = useMutation({
    mutationFn: (input: { a: string; b: string }) => api.diffMemberSnapshots(workspaceId, input.a, input.b),
    onSuccess: (data) => {
      setDiff(data)
      setPicked([])
    },
  })
  const restoreMutation = useMutation({
    mutationFn: () => api.restoreMemberSnapshot(workspaceId, aId, picked),
    onSuccess: () => {
      setDiff(null)
      void qc.invalidateQueries({ queryKey: ['new216-snapshots', workspaceId] })
    },
  })

  return (
    <div className="flex flex-col gap-3 text-sm" data-testid="new216-snapshots">
      <WorkspacePicker workspaceId={workspaceId} onChange={(id) => { setWorkspaceId(id); setDiff(null) }} />
      {workspaceId !== '' && (
        <>
          <div className="flex gap-1">
            <input
              aria-label="快照名称"
              className="flex-1 rounded border border-[var(--lumi-border)] px-2 py-1"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="快照名称"
            />
            <Button
              size="sm"
              disabled={name.trim() === '' || captureMutation.isPending}
              onClick={() => captureMutation.mutate()}
            >
              捕获
            </Button>
          </div>
          {captureMutation.isError && <p role="alert" className="text-sm text-[var(--lumi-danger)]">{errText(captureMutation.error)}</p>}
          {snapshots.isLoading ? (
            <Skeleton className="h-16" />
          ) : (snapshots.data?.items ?? []).length < 2 ? (
            <EmptyState icon={<FolderTree />} title="快照不足两张" description="至少两次快照才能比较差异。" />
          ) : (
            <div className="flex items-end gap-1">
              <Select
                aria-label="较早快照"
                value={aId}
                onChange={(event) => { setAId(event.target.value); setDiff(null) }}
                options={[{ value: '', label: '较早快照…' }, ...(snapshots.data?.items ?? []).map((s) => ({ value: s.id, label: `${s.name}（${s.refCount}）` }))]}
              />
              <Select
                aria-label="较晚快照"
                value={bId}
                onChange={(event) => { setBId(event.target.value); setDiff(null) }}
                options={[{ value: '', label: '较晚快照…' }, ...(snapshots.data?.items ?? []).map((s) => ({ value: s.id, label: `${s.name}（${s.refCount}）` }))]}
              />
              <Button
                size="sm"
                disabled={aId === '' || bId === ''}
                onClick={() => diffMutation.mutate({ a: aId, b: bId })}
              >
                比较差异
              </Button>
            </div>
          )}
          {diff !== null && (
            <div className="rounded border border-[var(--lumi-border)] p-2" data-testid="new216-diff">
              <p>新增 {diff.addedTotal} 篇 / 移除 {diff.removedTotal} 篇</p>
              <fieldset>
                <legend>勾选要恢复回集合的「移除」成员</legend>
                {diff.removed.length === 0 ? (
                  <p className="text-[var(--lumi-text-tertiary)]">没有被移除的成员。</p>
                ) : (
                  diff.removed.map((ref) => (
                    <label key={ref} className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={picked.includes(ref)}
                        onChange={(event) =>
                          setPicked((prev) =>
                            event.target.checked ? [...prev, ref] : prev.filter((r) => r !== ref),
                          )
                        }
                      />
                      <span className="truncate">{ref}</span>
                    </label>
                  ))
                )}
              </fieldset>
              <Button
                variant="primary"
                size="sm"
                disabled={picked.length === 0 || restoreMutation.isPending}
                onClick={() => restoreMutation.mutate()}
              >
                恢复所选
              </Button>
            </div>
          )}
          {restoreMutation.isError && <p role="alert" className="text-sm text-[var(--lumi-danger)]">{errText(restoreMutation.error)}</p>}
          {restoreMutation.isSuccess && (
            <p role="status" data-testid="new216-restore-result">
              已恢复 {restoreMutation.data.restored.length} 条（已存在 {restoreMutation.data.skippedExisting}，非法 {restoreMutation.data.invalidRefs}）。
            </p>
          )}
        </>
      )}
    </div>
  )
}

// ---- NEW-217 排序配方 -------------------------------------------------------

function RecipesSection() {
  const qc = useQueryClient()
  const [workspaceId, setWorkspaceId] = useState('')
  const recipes = useQuery({
    queryKey: ['new217-recipes', workspaceId],
    queryFn: () => api.listSortRecipes(workspaceId),
    enabled: workspaceId !== '',
  })
  const [name, setName] = useState('')
  const [exceptionsText, setExceptionsText] = useState('')
  const [preview, setPreview] = useState<{ explain: string; ordering: api.SortPreviewEntry[] } | null>(null)

  const createMutation = useMutation({
    mutationFn: () =>
      api.createSortRecipe(
        workspaceId,
        name,
        [
          { key: 'title', dir: 'asc' },
          { key: 'added_at', dir: 'desc' },
        ],
        exceptionsText
          .split(/\s+/)
          .map((ref) => ref.trim())
          .filter((ref) => ref !== ''),
      ),
    onSuccess: () => {
      setName('')
      setExceptionsText('')
      void qc.invalidateQueries({ queryKey: ['new217-recipes', workspaceId] })
    },
  })
  const previewMutation = useMutation({
    mutationFn: (recipeId: string) => api.previewSortRecipe(workspaceId, recipeId),
    onSuccess: setPreview,
  })
  const applyMutation = useMutation({
    mutationFn: (recipeId: string) => api.applySortRecipe(workspaceId, recipeId),
    onSuccess: () => setPreview(null),
  })
  const deleteMutation = useMutation({
    mutationFn: (recipeId: string) => api.deleteSortRecipe(workspaceId, recipeId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['new217-recipes', workspaceId] }),
  })

  return (
    <div className="flex flex-col gap-3 text-sm" data-testid="new217-recipes">
      <WorkspacePicker workspaceId={workspaceId} onChange={(id) => { setWorkspaceId(id); setPreview(null) }} />
      {workspaceId !== '' && (
        <>
          <div className="flex gap-1">
            <input
              aria-label="配方名称"
              className="flex-1 rounded border border-[var(--lumi-border)] px-2 py-1"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="配方名称（标题升序→加入时间降序）"
            />
            <Button
              size="sm"
              disabled={name.trim() === '' || createMutation.isPending}
              onClick={() => createMutation.mutate()}
            >
              保存配方
            </Button>
          </div>
          <input
            aria-label="固定例外（空格分隔）"
            className="rounded border border-[var(--lumi-border)] px-2 py-1 text-xs"
            value={exceptionsText}
            onChange={(event) => setExceptionsText(event.target.value)}
            placeholder="固定例外：始终置顶的引用（rss:… / library:…，空格分隔，可选）"
          />
          {createMutation.isError && <p role="alert" className="text-sm text-[var(--lumi-danger)]">{errText(createMutation.error)}</p>}
          {recipes.isLoading ? (
            <Skeleton className="h-16" />
          ) : (recipes.data?.items ?? []).length === 0 ? (
            <EmptyState title="该集合还没有排序配方" description="配方只影响这个集合，其他列表不受影响。" />
          ) : (
            <ul className="flex flex-col gap-2">
              {(recipes.data?.items ?? []).map((recipe) => (
                <li key={recipe.id} className="rounded border border-[var(--lumi-border)] p-2">
                  <p className="font-medium">{recipe.name}</p>
                  <p className="text-[var(--lumi-text-tertiary)]">{recipe.explain}</p>
                  <div className="mt-1 flex gap-1">
                    <Button size="sm" onClick={() => previewMutation.mutate(recipe.id)}>
                      预览
                    </Button>
                    <Button
                      variant="primary"
                      size="sm"
                      disabled={applyMutation.isPending}
                      onClick={() => applyMutation.mutate(recipe.id)}
                    >
                      应用排序
                    </Button>
                    <Button size="sm" disabled={deleteMutation.isPending} onClick={() => deleteMutation.mutate(recipe.id)}>
                      删除
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
          {preview !== null && (
            <div className="rounded border border-[var(--lumi-border)] p-2" data-testid="new217-preview">
              <p>{preview.explain}</p>
              <ol className="list-decimal pl-5">
                {preview.ordering.slice(0, 10).map((entry) => (
                  <li key={entry.ref}>
                    {entry.ref}
                    {entry.fixed ? '（固定）' : ''}
                  </li>
                ))}
              </ol>
            </div>
          )}
          {applyMutation.isError && <p role="alert" className="text-sm text-[var(--lumi-danger)]">{errText(applyMutation.error)}</p>}
          {applyMutation.isSuccess && <p role="status">已按配方排序（移动 {applyMutation.data.moved} 条）。</p>}
        </>
      )}
    </div>
  )
}

// ---- NEW-218 引用检查 -------------------------------------------------------

function ReferencesSection() {
  const qc = useQueryClient()
  const check = useQuery({ queryKey: ['new218-check'], queryFn: api.checkReferences })
  const [newRef, setNewRef] = useState('')
  const relinkMutation = useMutation({
    mutationFn: (issue: api.ReferenceIssue) => api.relinkReference(issue.surface, issue.locator, issue.ref, newRef),
    onSuccess: () => {
      setNewRef('')
      void qc.invalidateQueries({ queryKey: ['new218-check'] })
    },
  })
  const keepMutation = useMutation({
    mutationFn: (issue: api.ReferenceIssue) => api.keepStaleReference(issue.surface, issue.locator, issue.ref),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['new218-check'] }),
  })

  if (check.isLoading) return <Skeleton className="h-24" />
  if (check.isError) return <p role="alert" className="text-sm text-[var(--lumi-danger)]">{errText(check.error)}</p>
  const data = check.data
  return (
    <div className="flex flex-col gap-3 text-sm" data-testid="new218-references">
      <p className="text-[var(--lumi-text-tertiary)]">
        已检查 {data?.checked ?? 0} 个引用{data?.truncated ? '（有界截断，请分批处理）' : ''}
      </p>
      {(data?.issues ?? []).length === 0 ? (
        <EmptyState title="没有发现失效引用" />
      ) : (
        <ul className="flex flex-col gap-2">
          {(data?.issues ?? []).map((issue) => (
            <li key={`${issue.surface}:${issue.locator}:${issue.ref}`} className="rounded border border-[var(--lumi-border)] p-2">
              <p className="truncate">
                [{issue.surface}] {issue.ref}
              </p>
              <div className="mt-1 flex gap-1">
                <input
                  aria-label={`新目标 ${issue.ref}`}
                  className="flex-1 rounded border border-[var(--lumi-border)] px-2 py-1"
                  value={newRef}
                  onChange={(event) => setNewRef(event.target.value)}
                  placeholder="rss:… / library:…"
                />
                <Button
                  size="sm"
                  disabled={newRef.trim() === '' || relinkMutation.isPending}
                  onClick={() => relinkMutation.mutate(issue)}
                >
                  重新关联
                </Button>
                <Button size="sm" disabled={keepMutation.isPending} onClick={() => keepMutation.mutate(issue)}>
                  保留失效标记
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {relinkMutation.isError && <p role="alert" className="text-sm text-[var(--lumi-danger)]">{errText(relinkMutation.error)}</p>}
      {(data?.keptStale ?? []).length > 0 && (
        <p className="text-[var(--lumi-text-tertiary)]">已保留失效标记：{data?.keptStale.length} 处。</p>
      )}
    </div>
  )
}

export default function New216CollectionOpsPanel({ onClose }: { onClose: () => void }) {
  const [section, setSection] = useState<Section>('snapshots')
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3" data-testid="new216-panel">
      <div role="tablist" aria-label="集合整理分区" className="flex flex-wrap gap-1">
        {SECTIONS.map((item) => (
          <button
            key={item.key}
            role="tab"
            aria-selected={section === item.key}
            className={
              section === item.key
                ? 'rounded bg-[var(--lumi-surface-selected)] px-2 py-1 text-sm font-medium'
                : 'rounded px-2 py-1 text-sm text-[var(--lumi-text-secondary)]'
            }
            onClick={() => setSection(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {section === 'snapshots' && <SnapshotsSection />}
        {section === 'recipes' && <RecipesSection />}
        {section === 'references' && <ReferencesSection />}
      </div>
      <div className="flex justify-end">
        <Button size="sm" onClick={onClose}>
          关闭
        </Button>
      </div>
    </div>
  )
}
