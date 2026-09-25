/** WorkspaceCollectRulesPanel — N118 工作区自动收集规则区。
 *
 * 规则 = 来源条件（feedUrl | tag | keyword 恰好其一）+ 累计上限
 * （≤100）+ 开关。手动触发语义：预演（dry-run 有界 50）与应用
 * （命中条目以 ref 引用进工作区，幂等）都只由用户点按钮触发——
 * 绝不是后台抓取器，服务端没有任何任务读规则表。暂停 = enabled
 * 开关（set 语义非删除）；addedCount 到达上限后不再新增（诚实
 * capReached）。诚实状态：加载 / 空态 / 错误重试，与工作区页一致。
 */

import { useState } from 'react'
import { Inbox, Loader2, Pause, Play, Trash2 } from 'lucide-react'
import {
  useApplyCollectRuleMutation,
  useCreateCollectRuleMutation,
  useDeleteCollectRuleMutation,
  usePreviewCollectRuleMutation,
  useSetCollectRuleEnabledMutation,
  useWorkspaceCollectRules,
} from '../api/queries'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { Skeleton } from './ui/Skeleton'
import { cx } from './ui/cx'

type RuleSource = 'keyword' | 'feedUrl' | 'tag'

function ruleConditionLabel(rule: {
  feedUrl?: string | null
  tag?: string | null
  keyword?: string | null
}): string {
  if (rule.feedUrl !== null) return `来源 ${rule.feedUrl}`
  if (rule.tag !== null) return `标签「${rule.tag}」`
  if (rule.keyword !== null) return `关键词「${rule.keyword}」`
  return '（条件缺失）'
}

/** 预演结果 Dialog（dry-run：命中清单 + 既有成员标记，绝不写库）。 */
function PreviewDialog({
  workspaceId,
  ruleId,
  ruleLabel,
  onClose,
}: {
  workspaceId: string
  ruleId: string
  ruleLabel: string
  onClose: () => void
}) {
  const preview = usePreviewCollectRuleMutation()
  const apply = useApplyCollectRuleMutation()
  const data = preview.data

  return (
    <Dialog
      open
      onClose={onClose}
      title={`收集规则预演：${ruleLabel}`}
      panelClassName="max-w-lg"
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            关闭
          </Button>
          {data !== undefined && (
            <Button
              variant="primary"
              size="sm"
              disabled={apply.isPending || data.remainingCap === 0}
              onClick={() =>
                apply.mutate(
                  { workspaceId, ruleId },
                  { onSuccess: () => onClose() },
                )
              }
            >
              {apply.isPending ? '收集中…' : `收进工作区（剩余额度 ${data.remainingCap}）`}
            </Button>
          )}
        </div>
      }
    >
      <div className="flex flex-col gap-2" data-testid="collect-rule-preview">
        {preview.isPending && <Skeleton className="h-24 w-full" />}
        {preview.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {preview.error instanceof Error ? preview.error.message : '预演失败，请稍后重试。'}
          </p>
        )}
        {data !== undefined && (
          <>
            <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
              命中 {data.matchCount} 条
              {data.bounded ? '（预演只列前 50 条——完整收集同口径有界）' : ''}
              {data.alreadyMemberCount > 0 ? ` · ${data.alreadyMemberCount} 条已是工作区成员（幂等跳过）` : ''}
            </p>
            {data.matches.length === 0 ? (
              <p className="text-xs text-[var(--lumi-text-tertiary)]">投影中没有命中的条目。</p>
            ) : (
              <ul className="flex max-h-64 flex-col gap-1 overflow-y-auto">
                {data.matches.map((match) => (
                  <li
                    key={match.itemRef}
                    className="flex items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1 text-xs"
                  >
                    <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-primary)]">
                      {match.title ?? match.itemRef}
                    </span>
                    {match.alreadyMember && (
                      <span className="shrink-0 rounded-full bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-text-secondary)]">
                        已在
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
        {apply.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {apply.error instanceof Error ? apply.error.message : '收集失败，请稍后重试。'}
          </p>
        )}
      </div>
    </Dialog>
  )
}

/** N118 主面板：规则列表 + 新建 + 预演/应用/暂停/删除。 */
export function WorkspaceCollectRulesPanel({ workspaceId }: { workspaceId: string }) {
  const rules = useWorkspaceCollectRules(workspaceId)
  const create = useCreateCollectRuleMutation()
  const setEnabled = useSetCollectRuleEnabledMutation()
  const remove = useDeleteCollectRuleMutation()
  const [source, setSource] = useState<RuleSource>('keyword')
  const [value, setValue] = useState('')
  const [maxItems, setMaxItems] = useState(100)
  const [createError, setCreateError] = useState<string | null>(null)
  const [previewTarget, setPreviewTarget] = useState<{ id: string; label: string } | null>(null)

  function submitCreate(e: React.FormEvent) {
    e.preventDefault()
    setCreateError(null)
    const trimmed = value.trim()
    if (trimmed === '') return
    const body: Parameters<typeof create.mutate>[0]['body'] = { maxItems }
    if (source === 'keyword') body.keyword = trimmed
    else if (source === 'feedUrl') body.feedUrl = trimmed
    else body.tag = trimmed
    create.mutate(
      { workspaceId, body },
      {
        onSuccess: () => setValue(''),
        onError: (err) =>
          setCreateError(err instanceof Error ? err.message : '创建失败，请稍后重试。'),
      },
    )
  }

  const items = rules.data?.items ?? []

  return (
    <section
      data-workspace-collect-rules=""
      aria-label="收集规则"
      className="mt-4 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold text-[var(--lumi-text-primary)]">
          <Inbox aria-hidden className="size-4" />
          收集规则
        </h2>
        <span className="text-[11px] text-[var(--lumi-text-tertiary)]">
          手动触发 · 预演/收集只在你点按钮时执行，绝不后台抓取
        </span>
      </div>

      <form
        className="mt-2 flex flex-wrap items-center gap-1.5"
        onSubmit={submitCreate}
        data-collect-rule-create=""
      >
        <select
          value={source}
          onChange={(e) => setSource(e.target.value as RuleSource)}
          aria-label="规则条件类型"
          className="min-h-7 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5 text-xs text-[var(--lumi-text-primary)]"
        >
          <option value="keyword">关键词</option>
          <option value="feedUrl">来源 feed</option>
          <option value="tag">标签</option>
        </select>
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          aria-label="规则条件值"
          placeholder={source === 'feedUrl' ? 'https://feed.example/rss' : '如：检索'}
          className="min-h-7 w-44 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 text-xs text-[var(--lumi-text-primary)]"
        />
        <label className="flex items-center gap-1 text-[11px] text-[var(--lumi-text-tertiary)]">
          上限
          <input
            type="number"
            min={1}
            max={100}
            value={maxItems}
            onChange={(e) => setMaxItems(Number(e.target.value))}
            aria-label="收集上限"
            className="min-h-7 w-16 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5 text-xs text-[var(--lumi-text-primary)]"
          />
        </label>
        <Button type="submit" variant="secondary" size="sm" disabled={value.trim() === '' || create.isPending}>
          {create.isPending ? <Loader2 aria-hidden className="size-4 animate-spin" /> : null}
          新建规则
        </Button>
      </form>
      {createError !== null && (
        <p role="alert" className="mt-1.5 text-xs text-[var(--lumi-danger)]">
          {createError}
        </p>
      )}

      {rules.isPending ? (
        <Skeleton className="mt-2 h-12 w-full" />
      ) : rules.isError ? (
        <div className="mt-2" role="alert">
          <p className="text-xs text-[var(--lumi-danger)]">
            {rules.error instanceof Error ? rules.error.message : '规则加载失败。'}
          </p>
          <Button variant="secondary" size="sm" onClick={() => rules.refetch()}>
            重试
          </Button>
        </div>
      ) : items.length === 0 ? (
        <p className="mt-2 text-xs text-[var(--lumi-text-tertiary)]">
          还没有规则。新建后先「预演」看命中，再「收进工作区」（幂等，重复收集自动跳过）。
        </p>
      ) : (
        <ul className="mt-2 flex flex-col gap-1.5" aria-label="收集规则列表">
          {items.map((rule) => (
            <li
              key={rule.id}
              data-collect-rule={rule.id}
              className={cx(
                'flex flex-wrap items-center gap-2 rounded-[var(--lumi-radius-md)] border px-2.5 py-1.5 text-xs',
                rule.enabled
                  ? 'border-[var(--lumi-border)]'
                  : 'border-dashed border-[var(--lumi-border)] opacity-75',
              )}
            >
              <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-primary)]">
                {ruleConditionLabel(rule)}
                <span className="ml-2 text-[var(--lumi-text-tertiary)]">
                  已收 {rule.addedCount}/{rule.maxItems}
                </span>
                {!rule.enabled && (
                  <span className="ml-1.5 rounded-full bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-text-secondary)]">
                    已暂停
                  </span>
                )}
              </span>
              <Button variant="secondary" size="sm" onClick={() => setPreviewTarget({ id: rule.id, label: ruleConditionLabel(rule) })}>
                预演 / 收集
              </Button>
              <Button
                variant="ghost"
                size="sm"
                disabled={setEnabled.isPending}
                aria-label={rule.enabled ? `暂停规则 ${ruleConditionLabel(rule)}` : `恢复规则 ${ruleConditionLabel(rule)}`}
                onClick={() => setEnabled.mutate({ workspaceId, ruleId: rule.id, enabled: !rule.enabled })}
              >
                {rule.enabled ? (
                  <>
                    <Pause aria-hidden className="size-3.5" />
                    暂停
                  </>
                ) : (
                  <>
                    <Play aria-hidden className="size-3.5" />
                    恢复
                  </>
                )}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                disabled={remove.isPending}
                aria-label={`删除规则 ${ruleConditionLabel(rule)}`}
                onClick={() => remove.mutate({ workspaceId, ruleId: rule.id })}
              >
                <Trash2 aria-hidden className="size-3.5" />
                删除
              </Button>
            </li>
          ))}
        </ul>
      )}
      {previewTarget !== null && (
        <PreviewDialog
          workspaceId={workspaceId}
          ruleId={previewTarget.id}
          ruleLabel={previewTarget.label}
          onClose={() => setPreviewTarget(null)}
        />
      )}
    </section>
  )
}
