/** WorkspacePreviewPane — N103 临时预览面板。
 *
 * 工作区页内的预览窗格（非路由跳转）：展示 ResolvedItem 的诚实摘要
 * （标题/来源/时间/摘录/安全外链——绝不 innerHTML，上游内容仍由既有
 * DOMPurify 边界渲染）。关键契约：
 * - 同一时刻至多一个预览：打开另一个预览由父级整体替换本面板内容
 *   （parent 持有 preview 状态）；
 * - 预览笔记 = 设备本机草稿（lib/workspace-tabs.ts）：文本相对已保存
 *   草稿有改动即为「未保存」，父级据此拦截替换/关闭（诚实提示）；
 * - 添加到工作区（N103 提升动作）：条目已是成员时按钮不渲染
 *   （幂等由 BFF 兜底，UI 不提供重复入口）；关闭（N104）时由父级
 *   写入「最近关闭」。
 */

import { BookmarkPlus, ExternalLink, Loader2, Save, Trash2, X } from 'lucide-react'
import type { ReactNode } from 'react'
import { Button } from './ui/Button'
import { IconButton } from './ui/IconButton'
import { cx } from './ui/cx'

/** 预览目标：卡片 ResolvedItem 或最近关闭条目的最小公共形状。 */
export interface PreviewTarget {
  ref: string
  title: string
  url?: string | null
  kind?: string
  source?: string | null
  datetime?: string | null
  excerpt?: string | null
  stale?: boolean
}

export function WorkspacePreviewPane({
  target,
  draftText,
  onDraftChange,
  isMember,
  promotePending,
  onPromote,
  onClose,
}: {
  target: PreviewTarget
  /** 当前笔记草稿文本（父级持有，未保存拦截在父级判定）。 */
  draftText: string
  onDraftChange: (text: string) => void
  /** 条目已是工作区成员（true → 不渲染提升按钮）。 */
  isMember: boolean
  promotePending: boolean
  onPromote: () => void
  onClose: () => void
}) {
  const safeUrl =
    typeof target.url === 'string' && /^https?:\/\//i.test(target.url)
      ? target.url
      : null
  return (
    <section
      data-workspace-preview
      aria-label="内容预览"
      className={cx(
        'rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)]',
        'bg-[var(--lumi-surface)] p-3',
      )}
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-[var(--lumi-text-primary)]">
            {target.title}
          </h2>
          <p className="mt-0.5 text-xs text-[var(--lumi-text-tertiary)]">
            {[target.source, target.kind].filter(Boolean).join(' · ')}
            {target.datetime ? ` · ${target.datetime}` : ''}
          </p>
        </div>
        <IconButton
          icon={<X aria-hidden className="size-4" />}
          label="关闭预览"
          size="sm"
          touch
          onClick={onClose}
        />
      </div>
      {target.excerpt ? (
        <p className="mt-2 line-clamp-4 text-xs text-[var(--lumi-text-secondary)]">
          {target.excerpt}
        </p>
      ) : null}
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {safeUrl !== null && (
          <a
            href={safeUrl}
            target="_blank"
            rel="noreferrer noopener"
            className={cx(
              'inline-flex min-h-7 items-center gap-1 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-2.5 text-xs',
              'text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]',
            )}
          >
            <ExternalLink aria-hidden className="size-3.5" />
            原文链接
          </a>
        )}
        {!isMember && (
          <Button
            variant="secondary"
            size="sm"
            disabled={promotePending}
            onClick={onPromote}
          >
            {promotePending ? (
              <Loader2 aria-hidden className="size-4 animate-spin" />
            ) : (
              <BookmarkPlus aria-hidden className="size-4" />
            )}
            添加到工作区
          </Button>
        )}
        {isMember && (
          <span className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-2 py-0.5 text-[11px] text-[var(--lumi-text-secondary)]">
            已在工作区
          </span>
        )}
      </div>
      <label className="mt-3 flex flex-col gap-1">
        <span className="text-xs text-[var(--lumi-text-secondary)]">
          预览笔记（仅本机草稿）
        </span>
        <textarea
          value={draftText}
          onChange={(e) => onDraftChange(e.target.value)}
          rows={3}
          aria-label="预览笔记草稿"
          placeholder="随手记一点；替换/关闭预览前请先保存或放弃草稿。"
          className={cx(
            'w-full resize-y rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
            'px-3 py-2 text-sm text-[var(--lumi-text-primary)]',
            'placeholder:text-[var(--lumi-text-tertiary)]',
            'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
          )}
        />
      </label>
      <p className="mt-1 text-[11px] text-[var(--lumi-text-tertiary)]">
        草稿只保存在本机浏览器，不会同步到其他设备。
      </p>
    </section>
  )
}

/** 未保存草稿拦截提示（诚实文案 + 保存/放弃两个出口）。 */
export function PreviewDraftNotice({
  actions,
}: {
  actions: ReactNode
}): ReactNode {
  return (
    <div
      role="alert"
      data-testid="workspace-preview-blocked"
      className={cx(
        'flex flex-wrap items-center gap-2 rounded-[var(--lumi-radius-lg)] border px-3 py-2 text-xs',
        'border-[var(--lumi-border)] bg-[var(--lumi-surface)] text-[var(--lumi-text-secondary)]',
      )}
    >
      <span>当前预览有未保存的笔记草稿，已阻止替换——请先保存或放弃。</span>
      <span className="ml-auto flex items-center gap-1">{actions}</span>
    </div>
  )
}

/** 草稿动作按钮组（保存 / 放弃）。 */
export function PreviewDraftActions({
  onSave,
  onDiscard,
}: {
  onSave: () => void
  onDiscard: () => void
}): ReactNode {
  return (
    <>
      <Button variant="secondary" size="sm" onClick={onSave}>
        <Save aria-hidden className="size-4" />
        保存草稿
      </Button>
      <Button variant="ghost" size="sm" onClick={onDiscard}>
        <Trash2 aria-hidden className="size-4" />
        放弃草稿
      </Button>
    </>
  )
}
