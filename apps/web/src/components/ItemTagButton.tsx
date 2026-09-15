/** ItemTagButton — kind 无关的条目标签按钮（Q-P1-09）。
 *
 * 从 EntryActionButtons 的 EntryTagButton 提取：真值来源
 * GET /tags/item/{item_ref}（status='attached' 为勾选；'suggested' 行
 * 如实标注「建议」，仅显式勾选才绑定）。候选清单 = useTags 全量 ∪
 * 条目 suggested 独有行。loading / error / 空态齐备；新建走 assignTag
 * 的 upsert 语义。itemRef 是完整存储形态（rss:<id> / library:<uuid> /
 * …）——调用方决定域前缀，本组件绝不自行拼接。
 */

import { useMemo, useState } from 'react'
import { Loader2, Plus, Tags } from 'lucide-react'
import {
  useAssignTagMutation,
  useItemTags,
  useTags,
  useUnassignTagMutation,
} from '../api/queries'
import { IconButton } from './ui/IconButton'
import { Popover } from './ui/Popover'
import { cx } from './ui/cx'

export function ItemTagButton({
  itemRef,
  attachedCount,
  compact,
  idleCls,
}: {
  itemRef: string
  attachedCount: number
  compact?: boolean
  idleCls?: string
}) {
  const [newName, setNewName] = useState('')
  const allTags = useTags('')
  const itemTags = useItemTags(itemRef)
  const assign = useAssignTagMutation(itemRef)
  const unassign = useUnassignTagMutation(itemRef)

  // 解绑只在 attached 行上发生（suggested 从未绑定，无需解绑）。
  const attached = useMemo(
    () => new Map((itemTags.data?.items ?? []).filter((t) => t.status === 'attached').map((t) => [t.tagId, t.name])),
    [itemTags.data],
  )
  const suggestedNames = useMemo(
    () => new Set((itemTags.data?.items ?? []).filter((t) => t.status === 'suggested').map((t) => t.name)),
    [itemTags.data],
  )
  const allNames = useMemo(() => {
    const names = new Set<string>((allTags.data?.items ?? []).map((t) => t.name))
    for (const name of suggestedNames) names.add(name)
    return [...names].sort((a, b) => a.localeCompare(b, 'zh-CN'))
  }, [allTags.data, suggestedNames])

  // 候选清单是 useTags ∪ suggested 的并集；attached 的名字也可能不在
  // useTags（计数为 0 不出现？契约上 attached 必在列表——防御性并集）。
  const attachedNames = useMemo(() => new Set(attached.values()), [attached])

  const toggle = (name: string, nextAttached: boolean) => {
    if (nextAttached) assign.mutate(name)
    else unassign.mutate(name)
  }
  const createAndAssign = () => {
    const name = newName.trim()
    if (name === '' || assign.isPending) return
    assign.mutate(name, { onSuccess: () => setNewName('') })
  }

  const toggleError = assign.isError ? assign.error : unassign.isError ? unassign.error : null
  const pendingName = assign.isPending ? assign.variables : unassign.isPending ? unassign.variables : null
  const iconSize = compact ? 'size-4' : 'size-5'
  const active = attachedCount > 0

  return (
    <Popover
      width={240}
      trigger={({ triggerProps }) => (
        <IconButton
          {...triggerProps}
          icon={<Tags aria-hidden className={iconSize} />}
          label={active ? `标签（${attachedCount}）` : '标签'}
          title={active ? `标签（${attachedCount}）` : '标签'}
          size={compact ? 'sm' : 'md'}
          touch={!compact}
          className={cx(!active && idleCls)}
          style={{ color: active ? 'var(--lumi-accent)' : 'var(--lumi-text-tertiary)' }}
          onClick={(e) => {
            e.stopPropagation()
            triggerProps.onClick?.(e)
          }}
        />
      )}
    >
      {(close) => (
        <div className="flex max-h-64 flex-col gap-2" onClick={(e) => e.stopPropagation()}>
          <p className="text-xs font-medium text-[var(--lumi-text-secondary)]">标签</p>

          {allTags.isPending && itemTags.isPending && (
            <p className="text-xs text-[var(--lumi-text-tertiary)]" role="status" aria-label="标签加载中">
              标签加载中…
            </p>
          )}
          {(allTags.isError || itemTags.isError) && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">
              标签加载失败
              <button
                type="button"
                className="ml-1 underline"
                onClick={() => {
                  allTags.refetch()
                  void itemTags.refetch()
                }}
              >
                重试
              </button>
            </p>
          )}

          {allNames.length === 0 && !allTags.isPending && !itemTags.isPending ? (
            <p className="text-xs text-[var(--lumi-text-tertiary)]">暂无标签，可在下方新建。</p>
          ) : (
            <ul className="flex flex-col gap-0.5 overflow-y-auto">
              {allNames.map((name) => {
                const isChecked = attachedNames.has(name)
                const isSuggested = suggestedNames.has(name)
                const busy = pendingName === name
                return (
                  <li key={name}>
                    <label
                      className={cx(
                        'flex min-h-8 cursor-pointer items-center gap-2 rounded-[var(--lumi-radius-md)] px-1.5 text-xs',
                        'text-[var(--lumi-text-primary)] transition-colors duration-[var(--lumi-motion-fast)]',
                        'hover:bg-[var(--lumi-surface-hover)]',
                        busy && 'opacity-60',
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={isChecked}
                        disabled={busy}
                        onChange={() => toggle(name, !isChecked)}
                        aria-label={`标签 ${name}`}
                        className="size-3.5 accent-[var(--lumi-accent)]"
                      />
                      <span className="min-w-0 flex-1 truncate">#{name}</span>
                      {isSuggested && !isChecked && (
                        <span className="shrink-0 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-text-secondary)]">
                          建议
                        </span>
                      )}
                      {busy && <Loader2 aria-hidden className="size-3 shrink-0 animate-spin" />}
                    </label>
                  </li>
                )
              })}
            </ul>
          )}

          {/* 新建：本地输入 + 添加（assignTag upsert 语义：新名即建并绑定） */}
          <form
            className="flex items-center gap-1.5 border-t border-[var(--lumi-separator)] pt-2"
            onSubmit={(e) => {
              e.preventDefault()
              createAndAssign()
            }}
          >
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="新建标签"
              aria-label="新建标签"
              maxLength={64}
              className={cx(
                'min-h-8 min-w-0 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-xs text-[var(--lumi-text-primary)]',
                'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
              )}
            />
            <button
              type="submit"
              disabled={newName.trim() === '' || assign.isPending}
              aria-label="添加标签"
              title="添加标签"
              className={cx(
                'flex size-8 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)]',
                'text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)]',
                'hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
                'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                'disabled:cursor-default disabled:opacity-50',
              )}
            >
              {assign.isPending ? <Loader2 aria-hidden className="size-3.5 animate-spin" /> : <Plus aria-hidden className="size-3.5" />}
            </button>
          </form>

          {toggleError !== null && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">
              {toggleError instanceof Error ? toggleError.message : '标签操作失败，请稍后重试。'}
            </p>
          )}

          <button
            type="button"
            onClick={close}
            className="self-end text-xs text-[var(--lumi-text-secondary)] underline-offset-2 hover:underline"
          >
            完成
          </button>
        </div>
      )}
    </Popover>
  )
}
