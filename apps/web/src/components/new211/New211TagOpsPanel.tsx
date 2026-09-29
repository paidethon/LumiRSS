/** New211TagOpsPanel — NEW-211..215 标签整理工作台（GraphPage 挂载）。
 *
 * 五个分区（单 Dialog 内切换）：合并向导 / 改名影响图 / 互斥组 /
 * 同义词字典 / 使用清理台。全部只打 NEW 组端点；加载/空/错误三态齐全；
 * 合并前必须预览，删除带引用标签必须显式确认（acknowledgeReferences）。
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Tags } from 'lucide-react'
import * as api from './api'
import { ApiError } from './api'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Select } from '../ui/Select'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'

type Section = 'merge' | 'rename' | 'groups' | 'synonyms' | 'cleanup'

const SECTIONS: { key: Section; label: string }[] = [
  { key: 'merge', label: '合并向导' },
  { key: 'rename', label: '改名影响' },
  { key: 'groups', label: '互斥组' },
  { key: 'synonyms', label: '同义词' },
  { key: 'cleanup', label: '清理台' },
]

function errText(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return String(error)
}

function useTags() {
  return useQuery({ queryKey: ['new211-tags'], queryFn: api.listTags })
}

// ---- NEW-211 合并向导 -------------------------------------------------------

function MergeSection() {
  const qc = useQueryClient()
  const tags = useTags()
  const [sourceIds, setSourceIds] = useState<number[]>([])
  const [targetId, setTargetId] = useState<number | null>(null)
  const [preview, setPreview] = useState<api.MergeWizardPreview | null>(null)
  const [result, setResult] = useState<api.MergeWizardApplyResult | null>(null)
  const logs = useQuery({ queryKey: ['new211-merge-logs'], queryFn: api.mergeWizardLogs })

  const previewMutation = useMutation({
    mutationFn: () => api.mergeWizardPreview(sourceIds, targetId ?? 0),
    onSuccess: setPreview,
  })
  const applyMutation = useMutation({
    mutationFn: () => api.mergeWizardApply(sourceIds, targetId ?? 0),
    onSuccess: (data) => {
      setResult(data)
      setPreview(null)
      void qc.invalidateQueries({ queryKey: ['new211-tags'] })
      void qc.invalidateQueries({ queryKey: ['new211-merge-logs'] })
    },
  })
  const undoMutation = useMutation({
    mutationFn: (logId: string) => api.mergeWizardUndo(logId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['new211-tags'] })
      void qc.invalidateQueries({ queryKey: ['new211-merge-logs'] })
    },
  })

  if (tags.isLoading) return <Skeleton className="h-24" />
  if (tags.isError) return <p role="alert" className="text-sm text-[var(--lumi-danger)]">{errText(tags.error)}</p>
  const items = tags.data?.items ?? []
  if (items.length < 2) {
    return <EmptyState icon={<Tags />} title="标签还太少" description="至少需要两个标签才能合并。" />
  }

  return (
    <div className="flex flex-col gap-3 text-sm" data-testid="new211-merge">
      <fieldset>
        <legend className="mb-1 font-medium">选择要合并的源标签（可多选）</legend>
        <div className="flex max-h-32 flex-col gap-1 overflow-y-auto">
          {items.map((tag) => (
            <label key={tag.id} className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={sourceIds.includes(tag.id)}
                onChange={(event) =>
                  setSourceIds((prev) =>
                    event.target.checked ? [...prev, tag.id] : prev.filter((id) => id !== tag.id),
                  )
                }
              />
              {tag.name}（{tag.count}）
            </label>
          ))}
        </div>
      </fieldset>
      <Select
        aria-label="目标标签"
        value={targetId ?? ''}
        onChange={(event) => setTargetId(event.target.value === '' ? null : Number(event.target.value))}
        options={[{ value: '', label: '选择目标标签…' }, ...items.map((t) => ({ value: String(t.id), label: t.name }))]}
      />
      <Button
        size="sm"
        disabled={sourceIds.length === 0 || targetId === null || previewMutation.isPending}
        onClick={() => {
          setResult(null)
          previewMutation.mutate()
        }}
      >
        预览合并
      </Button>
      {previewMutation.isError && <p role="alert" className="text-sm text-[var(--lumi-danger)]">{errText(previewMutation.error)}</p>}
      {preview !== null && (
        <div className="rounded border border-[var(--lumi-border)] p-2" data-testid="new211-merge-preview">
          <p>
            受影响文章 <strong>{preview.affectedArticles}</strong> 篇；引用：同义词 {preview.references.synonyms}、
            互斥组 {preview.references.groupMemberships}
          </p>
          <ul className="list-disc pl-5">
            {preview.sources.map((s) => (
              <li key={s.tagId}>
                {s.name}：绑定 {s.bindings}，与目标重复 {s.overlaps}，将移动 {s.willMove}
              </li>
            ))}
          </ul>
          <Button
            variant="primary"
            size="sm"
            disabled={applyMutation.isPending}
            onClick={() => applyMutation.mutate()}
          >
            确认原子合并
          </Button>
        </div>
      )}
      {applyMutation.isError && <p role="alert" className="text-sm text-[var(--lumi-danger)]">{errText(applyMutation.error)}</p>}
      {result !== null && (
        <p role="status" data-testid="new211-merge-result">
          已合并到「{result.targetName}」（同义词同步 {result.synonymsSynced}，互斥组释放{' '}
          {result.groupMembershipsReleased}）。
        </p>
      )}
      {undoMutation.isError && <p role="alert" className="text-sm text-[var(--lumi-danger)]">{errText(undoMutation.error)}</p>}
      <div>
        <p className="mb-1 font-medium">可撤销记录（24 小时内）</p>
        {(logs.data?.items ?? []).length === 0 ? (
          <p className="text-[var(--lumi-text-tertiary)]">暂无合并记录。</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {(logs.data?.items ?? []).map((log) => (
              <li key={log.logId} className="flex items-center gap-2">
                <span>
                  → {log.targetName}（{log.sources.map((s) => s.name).join('、')}）
                </span>
                <Button size="sm" disabled={undoMutation.isPending} onClick={() => undoMutation.mutate(log.logId)}>
                  撤销
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

// ---- NEW-212 改名影响 -------------------------------------------------------

function RenameSection() {
  const qc = useQueryClient()
  const tags = useTags()
  const [tagId, setTagId] = useState<number | null>(null)
  const [newName, setNewName] = useState('')
  const [impact, setImpact] = useState<api.RenameImpact | null>(null)

  const impactMutation = useMutation({
    mutationFn: () => api.renameImpact(tagId ?? 0, newName),
    onSuccess: setImpact,
  })
  const applyMutation = useMutation({
    mutationFn: () => api.renameWithSync(tagId ?? 0, newName),
    onSuccess: () => {
      setImpact(null)
      void qc.invalidateQueries({ queryKey: ['new211-tags'] })
    },
  })

  if (tags.isLoading) return <Skeleton className="h-24" />
  const items = tags.data?.items ?? []
  if (items.length === 0) return <EmptyState title="还没有标签" />

  return (
    <div className="flex flex-col gap-3 text-sm" data-testid="new212-rename">
      <Select
        aria-label="要改名的标签"
        value={tagId ?? ''}
        onChange={(event) => setTagId(event.target.value === '' ? null : Number(event.target.value))}
        options={[{ value: '', label: '选择标签…' }, ...items.map((t) => ({ value: String(t.id), label: t.name }))]}
      />
      <input
        aria-label="新标签名"
        className="rounded border border-[var(--lumi-border)] px-2 py-1"
        value={newName}
        onChange={(event) => setNewName(event.target.value)}
        placeholder="新标签名"
      />
      <Button
        size="sm"
        disabled={tagId === null || newName.trim() === ''}
        onClick={() => impactMutation.mutate()}
      >
        查看影响
      </Button>
      {impactMutation.isError && <p role="alert" className="text-sm text-[var(--lumi-danger)]">{errText(impactMutation.error)}</p>}
      {impact !== null && (
        <div className="rounded border border-[var(--lumi-border)] p-2" data-testid="new212-impact">
          <p>
            {impact.oldName} → {impact.newName}；受影响绑定 {impact.bindings} 条
          </p>
          <p>将同步改写：{impact.willRewrite.length === 0 ? '无（没有名字键引用）' : `${impact.willRewrite.length} 条同义词`}</p>
          <p>自动跟随（无需改写）：{impact.autoFollow.length} 处</p>
          <Button variant="primary" size="sm" disabled={applyMutation.isPending} onClick={() => applyMutation.mutate()}>
            确认改名并同步
          </Button>
        </div>
      )}
      {applyMutation.isError && <p role="alert" className="text-sm text-[var(--lumi-danger)]">{errText(applyMutation.error)}</p>}
      {applyMutation.isSuccess && (
        <p role="status" data-testid="new212-rename-result">
          已改名（同义词改写 {applyMutation.data.synonymsRewritten} 条，绑定跟随 {applyMutation.data.bindingsFollowed} 条）。
        </p>
      )}
    </div>
  )
}

// ---- NEW-213 互斥组 ---------------------------------------------------------

function GroupsSection() {
  const qc = useQueryClient()
  const groups = useQuery({ queryKey: ['new213-groups'], queryFn: api.listTagGroups })
  const tags = useTags()
  const [name, setName] = useState('')
  const [members, setMembers] = useState<string[]>([])
  const [openGroupId, setOpenGroupId] = useState<number | null>(null)
  const conflicts = useQuery({
    queryKey: ['new213-conflicts', openGroupId],
    queryFn: () => api.tagGroupConflicts(openGroupId ?? 0),
    enabled: openGroupId !== null,
  })
  const createMutation = useMutation({
    mutationFn: () => api.createTagGroup(name, members),
    onSuccess: () => {
      setName('')
      setMembers([])
      void qc.invalidateQueries({ queryKey: ['new213-groups'] })
    },
  })
  const resolveMutation = useMutation({
    mutationFn: (input: { ref: string; keep: string }) =>
      api.resolveTagGroup(openGroupId ?? 0, [input]),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['new213-conflicts'] }),
  })

  return (
    <div className="flex flex-col gap-3 text-sm" data-testid="new213-groups">
      <div className="flex flex-col gap-1">
        <input
          aria-label="互斥组名称"
          className="rounded border border-[var(--lumi-border)] px-2 py-1"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="组名（如：温度）"
        />
        <fieldset>
          <legend className="font-medium">成员（至少 2 个）</legend>
          <div className="flex max-h-24 flex-wrap gap-2">
            {(tags.data?.items ?? []).map((tag) => (
              <label key={tag.id} className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={members.includes(tag.name)}
                  onChange={(event) =>
                    setMembers((prev) =>
                      event.target.checked ? [...prev, tag.name] : prev.filter((m) => m !== tag.name),
                    )
                  }
                />
                {tag.name}
              </label>
            ))}
          </div>
        </fieldset>
        <Button
          size="sm"
          disabled={name.trim() === '' || members.length < 2 || createMutation.isPending}
          onClick={() => createMutation.mutate()}
        >
          创建互斥组
        </Button>
        {createMutation.isError && <p role="alert" className="text-sm text-[var(--lumi-danger)]">{errText(createMutation.error)}</p>}
      </div>
      {groups.isLoading ? (
        <Skeleton className="h-16" />
      ) : (groups.data?.items ?? []).length === 0 ? (
        <EmptyState title="还没有互斥组" description="定义后，组内标签在同一内容上至多保留一个。" />
      ) : (
        <ul className="flex flex-col gap-2">
          {(groups.data?.items ?? []).map((group) => (
            <li key={group.id} className="rounded border border-[var(--lumi-border)] p-2">
              <div className="flex items-center justify-between">
                <span className="font-medium">{group.name}</span>
                <Button
                  size="sm"
                  onClick={() => setOpenGroupId((prev) => (prev === group.id ? null : group.id))}
                >
                  {openGroupId === group.id ? '收起冲突' : '查看冲突'}
                </Button>
              </div>
              <p className="text-[var(--lumi-text-tertiary)]">成员：{group.members.map((m) => m.name).join('、')}</p>
              {openGroupId === group.id && (
                <div data-testid="new213-conflicts">
                  {conflicts.isLoading ? (
                    <Skeleton className="h-10" />
                  ) : (conflicts.data?.items ?? []).length === 0 ? (
                    <p className="text-[var(--lumi-text-tertiary)]">当前没有冲突。</p>
                  ) : (
                    (conflicts.data?.items ?? []).map((item) => (
                      <div key={item.ref} className="mt-1 flex items-center gap-2">
                        <span className="truncate">{item.ref}</span>
                        <Select
                          aria-label={`保留值 ${item.ref}`}
                          value=""
                          onChange={(event) =>
                            resolveMutation.mutate({ ref: item.ref, keep: event.target.value })
                          }
                          options={[
                            { value: '', label: '保留…' },
                            ...item.tags.map((t) => ({ value: t.name, label: t.name })),
                          ]}
                        />
                      </div>
                    ))
                  )}
                  {resolveMutation.isError && (
                    <p role="alert" className="text-sm text-[var(--lumi-danger)]">{errText(resolveMutation.error)}</p>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---- NEW-214 同义词 ---------------------------------------------------------

function SynonymsSection() {
  const qc = useQueryClient()
  const synonyms = useQuery({ queryKey: ['new214-synonyms'], queryFn: api.listTagSynonyms })
  const tags = useTags()
  const [alias, setAlias] = useState('')
  const [canonical, setCanonical] = useState('')
  const [probe, setProbe] = useState<api.TagSynonymResolve | null>(null)

  const createMutation = useMutation({
    mutationFn: () => api.createTagSynonym(alias, canonical),
    onSuccess: () => {
      setAlias('')
      setCanonical('')
      void qc.invalidateQueries({ queryKey: ['new214-synonyms'] })
    },
  })
  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteTagSynonym(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['new214-synonyms'] }),
  })
  const probeMutation = useMutation({
    mutationFn: (input: string) => api.resolveTagSynonym(input),
    onSuccess: setProbe,
  })

  return (
    <div className="flex flex-col gap-3 text-sm" data-testid="new214-synonyms">
      <div className="flex flex-col gap-1">
        <input
          aria-label="别名"
          className="rounded border border-[var(--lumi-border)] px-2 py-1"
          value={alias}
          onChange={(event) => setAlias(event.target.value)}
          placeholder="别名（如 AI）"
        />
        <Select
          aria-label="规范标签"
          value={canonical}
          onChange={(event) => setCanonical(event.target.value)}
          options={[
            { value: '', label: '规范标签…' },
            ...(tags.data?.items ?? []).map((t) => ({ value: t.name, label: t.name })),
          ]}
        />
        <Button
          size="sm"
          disabled={alias.trim() === '' || canonical === '' || createMutation.isPending}
          onClick={() => createMutation.mutate()}
        >
          登记别名
        </Button>
        {createMutation.isError && <p role="alert" className="text-sm text-[var(--lumi-danger)]">{errText(createMutation.error)}</p>}
        <div className="flex gap-1">
          <input
            aria-label="试试输入提示"
            className="flex-1 rounded border border-[var(--lumi-border)] px-2 py-1"
            value={alias}
            onChange={(event) => setAlias(event.target.value)}
            placeholder="输入试试规范提示…"
          />
          <Button size="sm" disabled={alias.trim() === ''} onClick={() => probeMutation.mutate(alias)}>
            提示
          </Button>
        </div>
        {probe !== null && (
          <p role="status" data-testid="new214-probe">
            {probe.exact && probe.canonical !== null
              ? `规范标签：${probe.canonical}`
              : probe.suggestions.length > 0
                ? `候选：${probe.suggestions.join('、')}`
                : '没有匹配的别名或标签。'}
          </p>
        )}
      </div>
      {synonyms.isLoading ? (
        <Skeleton className="h-16" />
      ) : (synonyms.data?.items ?? []).length === 0 ? (
        <EmptyState title="还没有别名" description="别名只影响录入提示，绝不改写文章原文。" />
      ) : (
        <ul className="flex flex-col gap-1">
          {(synonyms.data?.items ?? []).map((entry) => (
            <li key={entry.id} className="flex items-center justify-between gap-2">
              <span>
                {entry.alias} → {entry.canonical}
              </span>
              <Button size="sm" disabled={deleteMutation.isPending} onClick={() => deleteMutation.mutate(entry.id)}>
                删除
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---- NEW-215 清理台 ---------------------------------------------------------

function CleanupSection() {
  const qc = useQueryClient()
  const report = useQuery({ queryKey: ['new215-report'], queryFn: api.tagCleanupReport })
  const [ack, setAck] = useState(false)
  const deleteMutation = useMutation({
    mutationFn: (input: { tagIds: number[]; ack: boolean }) =>
      api.tagCleanupDelete(input.tagIds, input.ack),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['new215-report'] }),
  })

  if (report.isLoading) return <Skeleton className="h-24" />
  if (report.isError) return <p role="alert" className="text-sm text-[var(--lumi-danger)]">{errText(report.error)}</p>
  const buckets = report.data?.buckets
  const blocked = deleteMutation.error instanceof ApiError && deleteMutation.error.type === 'tag_cleanup_blocked'

  const bucketView = (title: string, entries: api.TagCleanupEntry[], deletable: boolean) => (
    <div>
      <p className="font-medium">
        {title}（{entries.length}）
      </p>
      {entries.length === 0 ? (
        <p className="text-[var(--lumi-text-tertiary)]">无</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {entries.map((entry) => (
            <li key={entry.tagId} className="flex items-center justify-between gap-2">
              <span>
                {entry.name}
                {deletable ? '' : `（引用：同义词 ${entry.references.synonyms} / 互斥组 ${entry.references.groupMemberships}）`}
              </span>
              {deletable ? (
                <Button
                  size="sm"
                  disabled={deleteMutation.isPending}
                  onClick={() => deleteMutation.mutate({ tagIds: [entry.tagId], ack: false })}
                >
                  删除
                </Button>
              ) : (
                <Button
                  size="sm"
                  disabled={deleteMutation.isPending || !ack}
                  onClick={() => deleteMutation.mutate({ tagIds: [entry.tagId], ack: true })}
                >
                  确认并删
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )

  return (
    <div className="flex flex-col gap-3 text-sm" data-testid="new215-cleanup">
      {buckets && (
        <>
          {bucketView('无人使用', buckets.unused, true)}
          {bucketView('仅规则引用', buckets.referencedOnly, false)}
          {bucketView('仍有关联内容', buckets.inUse, false)}
        </>
      )}
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={ack} onChange={(event) => setAck(event.target.checked)} />
        我知道删除会一并清理这些引用
      </label>
      {blocked && (
        <p role="alert" className="text-sm text-[var(--lumi-danger)]" data-testid="new215-blocked">
          {errText(deleteMutation.error)}（先勾选确认）
        </p>
      )}
      {!blocked && deleteMutation.isError && (
        <p role="alert" className="text-sm text-[var(--lumi-danger)]">{errText(deleteMutation.error)}</p>
      )}
      {deleteMutation.isSuccess && (
        <p role="status">已删除 {deleteMutation.data.deleted.length} 个标签及对应引用。</p>
      )}
    </div>
  )
}

// ---- 面板外壳 ---------------------------------------------------------------

export default function New211TagOpsPanel({ onClose }: { onClose: () => void }) {
  const [section, setSection] = useState<Section>('merge')
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3" data-testid="new211-panel">
      <div role="tablist" aria-label="标签整理分区" className="flex flex-wrap gap-1">
        {SECTIONS.map((item) => (
          <button
            key={item.key}
            role="tab"
            aria-selected={section === item.key}
            className={cx(
              'rounded px-2 py-1 text-sm',
              section === item.key
                ? 'bg-[var(--lumi-surface-selected)] font-medium'
                : 'text-[var(--lumi-text-secondary)]',
            )}
            onClick={() => setSection(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {section === 'merge' && <MergeSection />}
        {section === 'rename' && <RenameSection />}
        {section === 'groups' && <GroupsSection />}
        {section === 'synonyms' && <SynonymsSection />}
        {section === 'cleanup' && <CleanupSection />}
      </div>
      <div className="flex justify-end">
        <Button size="sm" onClick={onClose}>
          关闭
        </Button>
      </div>
    </div>
  )
}
