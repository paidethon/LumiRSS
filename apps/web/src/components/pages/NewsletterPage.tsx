/** NewsletterPage — 邮件简报（外发摘要）已发送内容页（R19）。
 *
 * 数据真源：/api/v1/newsletter/issues（deliver_digest 的逐次发送
 * 账本）。默认 tab「已发送」，可切草稿/计划/失败：
 * - 已发送行回看正文快照（HTML 渲染前必过 lib/sanitize-article-html
 *   的 DOMPurify 边界——全站唯一正文净化入口；text 形态直接按文本渲染）；
 * - 失败行显示错误与重试入口：重试只投递账目中尚未成功的收件人
 *   （服务端逐收件人记账），成功后刷新列表/详情；
 * - 无正文快照的记录（失败行/历史形态）诚实显示「历史记录不可用」，
 *   绝不伪造正文；
 * - 「管理连接/发送设置」深链设置 mail 分类（settings-bridge）。
 *
 * 领域区分（页内常驻说明）：「外部邮件订阅收件箱」收外部邮件进
 * bridge 列表；本页是「外发简报」——LumiRSS 按配置经自己的 SMTP
 * 中继把摘要发给收件人。两者同属邮件域但数据与操作互不相通。
 *
 * 挂载语义（App.tsx 由主 Agent 接）：桌面加入 FULL_WIDTH_SECTIONS
 * 独占主区；移动端挂顶部 section 区。本组件只提供自洽的
 * min-h-0 flex 列布局，两种挂载位同构可用。
 */

import { useState } from 'react'
import {
  AlertTriangle,
  Inbox,
  MailWarning,
  RotateCcw,
  Settings2,
} from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getNewsletterIssue,
  listNewsletterIssues,
  retryNewsletterIssue,
  type NewsletterIssueDetail,
  type NewsletterIssueStatus,
  type NewsletterIssueSummary,
} from '../../api/newsletter'
import { formatTimestamp } from '../../lib/date-format'
import { sanitizeArticleHtml } from '../../lib/sanitize-article-html'
import { Button } from '../ui/Button'
import { DetailDrawer } from '../ui/DetailDrawer'
import { EmptyState } from '../ui/EmptyState'
import { PageHeader } from '../ui/PageHeader'
import { Skeleton } from '../ui/Skeleton'
import { Tabs } from '../ui/Tabs'
import { Toolbar } from '../ui/Toolbar'
import { cx } from '../ui/cx'
import { requestOpenSettings } from '../settings/settings-bridge'

const STATUS_TABS: ReadonlyArray<{ value: NewsletterIssueStatus; label: string }> = [
  { value: 'sent', label: '已发送' },
  { value: 'draft', label: '草稿' },
  { value: 'scheduled', label: '计划' },
  { value: 'failed', label: '失败' },
]

const EMPTY_COPY: Record<NewsletterIssueStatus, { title: string; description: string }> = {
  sent: {
    title: '还没有已发送的简报',
    description: '在设置里完成 SMTP 配置后「立即发送」，发送记录会出现在这里。',
  },
  draft: {
    title: '外发简报没有草稿',
    description: '简报内容由服务端在发送时即时汇总，不产生草稿；预览在设置的发送页。',
  },
  scheduled: {
    title: '暂无计划发送记录',
    description: '计划发送在设置中按小时启用；到点发出后，记录会进入「已发送」。',
  },
  failed: {
    title: '没有失败的发送',
    description: '发送失败会留在这里，可对尚未送达的收件人重试。',
  },
}

const STATUS_BADGE: Record<string, { label: string; className: string }> = {
  sent: {
    label: '已发送',
    className: 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-secondary)]',
  },
  failed: {
    label: '失败',
    className: 'bg-[var(--lumi-danger-soft)] text-[var(--lumi-danger)]',
  },
  draft: { label: '草稿', className: 'bg-[var(--lumi-surface-hover)]' },
  scheduled: { label: '计划', className: 'bg-[var(--lumi-surface-hover)]' },
}

export default function NewsletterPage() {
  const [status, setStatus] = useState<NewsletterIssueStatus>('sent')
  const [openId, setOpenId] = useState<number | null>(null)

  const openDetail = useQuery({
    queryKey: ['newsletter-issue', openId],
    queryFn: ({ signal }) => getNewsletterIssue(openId as number, signal),
    enabled: openId !== null,
  })

  return (
    <div className="flex min-h-0 flex-1 flex-col" aria-label="邮件简报">
      <div className="min-h-0 flex-1 overflow-y-auto p-3 max-lg:pb-[calc(4.75rem_+_var(--safe-bottom))]">
        <PageHeader
          title="邮件简报"
          subtitle="外发摘要的发送记录——已发送内容可回看，失败可对未送达收件人重试"
          actions={
            <Button
              variant="secondary"
              size="sm"
              onClick={() => requestOpenSettings('mail')}
            >
              <Settings2 aria-hidden="true" className="size-4 shrink-0" />
              管理连接/发送设置
            </Button>
          }
        />

        {/* 领域区分标签：收件箱 ≠ 外发简报（同属邮件域，互不相通）。 */}
        <p className="mt-2 flex items-start gap-1.5 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
          <Inbox aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
          <span>
            这里是<strong className="font-medium text-[var(--lumi-text-secondary)]">外发简报</strong>
            （LumiRSS 经你的 SMTP 中继发出的摘要）；外部邮件订阅的收件在设置的「邮件简报」连接管理里。
          </span>
        </p>

        <Toolbar
          aria-label="简报操作"
          className="mt-3"
          actions={[
            {
              id: 'settings',
              label: '管理连接/发送设置',
              icon: <Settings2 aria-hidden="true" className="size-3.5" />,
              onSelect: () => requestOpenSettings('mail'),
            },
          ]}
        />

        <Tabs
          aria-label="简报状态"
          className="mt-3"
          value={status}
          onValueChange={setStatus}
          options={STATUS_TABS}
          panels={{
            sent: <IssueListPanel status="sent" onOpen={setOpenId} />,
            draft: <IssueListPanel status="draft" onOpen={setOpenId} />,
            scheduled: <IssueListPanel status="scheduled" onOpen={setOpenId} />,
            failed: <IssueListPanel status="failed" onOpen={setOpenId} />,
          }}
        />
      </div>

      <DetailDrawer
        open={openId !== null}
        onClose={() => setOpenId(null)}
        title={openDetail.data?.subject ?? '简报详情'}
      >
        {openDetail.data !== undefined ? (
          <IssueDetailBody detail={openDetail.data} />
        ) : openDetail.isError ? (
          <EmptyState
            icon={<AlertTriangle aria-hidden className="size-6 text-[var(--lumi-danger)]" />}
            title="详情加载失败"
            description={openDetail.error instanceof Error ? openDetail.error.message : '请稍后重试。'}
            action={
              <Button variant="secondary" size="sm" onClick={() => void openDetail.refetch()}>
                重试
              </Button>
            }
          />
        ) : (
          <div className="flex flex-col gap-2" aria-busy="true">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-40 w-full" />
          </div>
        )}
      </DetailDrawer>
    </div>
  )
}

// ---- 状态列表面板 -------------------------------------------------------------

function IssueListPanel({
  status,
  onOpen,
}: {
  status: NewsletterIssueStatus
  onOpen: (id: number) => void
}) {
  const list = useQuery({
    queryKey: ['newsletter-issues', status],
    queryFn: ({ signal }) => listNewsletterIssues(status, signal),
  })

  if (list.isPending) {
    return (
      <div className="flex flex-col gap-2" aria-busy="true" aria-label="简报列表加载中">
        <Skeleton className="h-11 w-full" />
        <Skeleton className="h-11 w-full" />
        <Skeleton className="h-11 w-full" />
      </div>
    )
  }
  if (list.isError || list.data === undefined) {
    return (
      <EmptyState
        icon={<AlertTriangle aria-hidden className="size-6 text-[var(--lumi-danger)]" />}
        title="发送记录加载失败"
        description={list.error instanceof Error ? list.error.message : '请稍后重试。'}
        action={
          <Button variant="secondary" size="sm" onClick={() => void list.refetch()}>
            重试
          </Button>
        }
      />
    )
  }
  const items = list.data.items
  if (items.length === 0) {
    const copy = EMPTY_COPY[status]
    return (
      <EmptyState
        icon={<MailWarning aria-hidden className="size-8" />}
        title={copy.title}
        description={copy.description}
        action={
          status === 'scheduled' || status === 'draft' ? (
            <Button variant="secondary" size="sm" onClick={() => requestOpenSettings('mail')}>
              打开发送设置
            </Button>
          ) : undefined
        }
      />
    )
  }
  return (
    <ul className="flex flex-col gap-1.5" aria-label={`简报记录（${items.length} 条）`}>
      {items.map((issue) => (
        <IssueRow key={issue.id} issue={issue} onOpen={onOpen} />
      ))}
    </ul>
  )
}

function IssueRow({
  issue,
  onOpen,
}: {
  issue: NewsletterIssueSummary
  onOpen: (id: number) => void
}) {
  const badge = STATUS_BADGE[issue.status] ?? STATUS_BADGE.draft
  return (
    <li>
      <button
        type="button"
        onClick={() => onOpen(issue.id)}
        className={cx(
          'flex min-h-11 w-full flex-col gap-0.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-3 py-2 text-left',
          'transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]',
          'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
        )}
      >
        <span className="flex min-w-0 items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-[var(--lumi-text-primary)]">
            {issue.subject || '（无主题）'}
          </span>
          <span
            className={cx(
              'shrink-0 rounded-[var(--lumi-radius-sm)] px-1.5 py-0.5 text-[0.6875rem] leading-none',
              badge.className,
            )}
          >
            {badge.label}
          </span>
        </span>
        <span className="flex min-w-0 flex-wrap items-center gap-x-2 text-xs text-[var(--lumi-text-tertiary)]">
          <span>{formatTimestamp(issue.sentAt ?? issue.createdAt) || '—'}</span>
          <span aria-hidden="true">·</span>
          <span>来源 {issue.source || '—'}</span>
          <span aria-hidden="true">·</span>
          <span>
            {issue.origin === 'scheduled' ? '定时' : '手动'} · {issue.recipientCount} 个收件人
          </span>
          {issue.status === 'failed' && issue.error !== null && (
            <span className="w-full truncate text-[var(--lumi-danger)]">{issue.error}</span>
          )}
        </span>
      </button>
    </li>
  )
}

// ---- 详情（正文快照 / 历史不可用 / 重试） ---------------------------------------

function IssueDetailBody({ detail }: { detail: NewsletterIssueDetail }) {
  const queryClient = useQueryClient()
  const retry = useMutation({
    mutationFn: () => retryNewsletterIssue(detail.id),
    onSuccess: () => {
      // 抽屉保持打开：失效后重取，用户直接看到补发结果与新状态。
      void queryClient.invalidateQueries({ queryKey: ['newsletter-issues'] })
      void queryClient.invalidateQueries({ queryKey: ['newsletter-issue', detail.id] })
    },
  })

  return (
    <div className="flex flex-col gap-3">
      <dl className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
        <DetailRow label="状态" value={STATUS_BADGE[detail.status]?.label ?? detail.status} />
        <DetailRow
          label={detail.sentAt !== null ? '发送时间' : '创建时间'}
          value={formatTimestamp(detail.sentAt ?? detail.createdAt) || '—'}
        />
        <DetailRow label="来源" value={detail.source || '—'} />
        <DetailRow label="发送方式" value={detail.origin === 'scheduled' ? '定时调度' : '手动'} />
        <DetailRow label="条目数" value={String(detail.itemCount)} />
        <DetailRow label="收件人" value={`${detail.recipientCount} 个`} />
        {detail.recipients.length > 0 && (
          <DetailRow
            label="收件账目"
            value={detail.recipients
              .map((r) => `${r.address}（${r.status === 'sent' ? '已送达' : '未送达'}）`)
              .join('、')}
          />
        )}
        {detail.error !== null && (
          <DetailRow label="错误" value={detail.error} tone="danger" />
        )}
      </dl>

      {detail.bodyAvailable ? (
        detail.html !== null ? (
          // 安全边界：正文快照经 sanitizeArticleHtml（DOMPurify）清洗后渲染。
          <div
            className="min-w-0 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3 text-sm leading-relaxed text-[var(--lumi-text-primary)] [&_a]:break-all"
            data-testid="newsletter-body"
            dangerouslySetInnerHTML={{ __html: sanitizeArticleHtml(detail.html) }}
          />
        ) : (
          <pre className="min-w-0 overflow-x-auto whitespace-pre-wrap rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3 font-sans text-sm leading-relaxed text-[var(--lumi-text-primary)]" data-testid="newsletter-body">
            {detail.text}
          </pre>
        )
      ) : (
        <EmptyState
          icon={<MailWarning aria-hidden className="size-6" />}
          title="历史记录不可用"
          description="这条记录没有保留正文快照（失败或更早的记录形态），无法回看内容。"
        />
      )}

      {detail.status === 'failed' && (
        <div className="flex flex-col gap-1.5">
          <Button
            variant="primary"
            size="sm"
            className="max-lg:min-h-11"
            onClick={() => retry.mutate()}
            disabled={retry.isPending}
            aria-busy={retry.isPending}
          >
            <RotateCcw aria-hidden="true" className="size-4 shrink-0" />
            {retry.isPending ? '重试中…' : '重试未送达的收件人'}
          </Button>
          {retry.isError && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">
              {retry.error instanceof Error ? retry.error.message : '重试失败，请稍后再试。'}
            </p>
          )}
          {retry.isSuccess && (
            <p className="text-xs text-[var(--lumi-text-secondary)]">
              已补发 {retry.data.sentCount} 个收件人，跳过 {retry.data.skippedCount} 个已送达。
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function DetailRow({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone?: 'danger'
}) {
  return (
    <div className="flex min-w-0 items-baseline gap-2">
      <dt className="w-16 shrink-0 text-[var(--lumi-text-tertiary)]">{label}</dt>
      <dd
        className={cx(
          'min-w-0 flex-1 break-words',
          tone === 'danger' ? 'text-[var(--lumi-danger)]' : 'text-[var(--lumi-text-secondary)]',
        )}
      >
        {value}
      </dd>
    </div>
  )
}
