/** InboxPage — 收件箱（0021 推送来源 Knowledge Workbench 纵向切片）。
 *
 * BFF：/api/v1/inbox/sources（连接器管理）+ /api/v1/inbox/items（裸
 * ItemRef 分页）+ POST /api/v1/resolve（统一卡片）。外部脚本/Agent 向
 * /api/v1/inbox/ingest/{uuid} 携带 bearer secret 推送 JSON，内容即成为
 * Lumi 拥有的 api_item —— 本页是它的工作台入口。职责：
 * - 连接器管理：新建（secret 仅创建时展示一次 + 摄取路径复制）、
 *   删除（连带全部条目，无二次确认——与时间线诚实语义一致）；
 * - 条目列表：UnifiedContentCard 渲染（域徽标「收件」+ per-kind 打开
 *   路由），加入稍后读（服务端工作区，跨设备可见）、行内删除；
 * - 诚实状态：加载 Skeleton / 空态 / 错误重试 / 加载更多；
 *   stale 条目照常渲染并给「建议移除」提示。
 *
 * 安全：secret 永不落 localStorage；创建成功 Dialog 关闭后即不可再取。
 */

import { useMemo, useState } from 'react'
import {
  Copy,
  Inbox as InboxIcon,
  Loader2,
  Plus,
  Trash2,
} from 'lucide-react'
import {
  useCreateInboxSourceMutation,
  useDeleteInboxItemMutation,
  useDeleteInboxSourceMutation,
  useAddWorkspaceItemMutation,
  useInboxItems,
  useInboxSources,
  useResolveRefs,
} from '../../api/queries'
import type { InboxSourceCreated } from '../../api/types'
import { READ_LATER_WORKSPACE_ID } from '../../lib/read-later'
import { Button } from '../ui/Button'
import { Dialog } from '../ui/Dialog'
import { EmptyState } from '../ui/EmptyState'
import { IconButton } from '../ui/IconButton'
import { Skeleton } from '../ui/Skeleton'
import UnifiedContentCard from '../UnifiedContentCard'
import { cx } from '../ui/cx'

/** 新建连接器 Dialog：名称输入；成功后展示一次性 secret + 摄取路径。 */
function CreateConnectorDialog({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState('')
  const [created, setCreated] = useState<InboxSourceCreated | null>(null)
  const create = useCreateInboxSourceMutation()
  const canSubmit = name.trim() !== '' && !create.isPending

  const copy = (text: string) => {
    void navigator.clipboard?.writeText(text).catch(() => {})
  }

  // ingest 是机器对机器入口：推送方通常在另一台机器上，相对路径复制
  // 出去不可用（P0-06g 在 mail 域的修复，0021 曾原样复发——Q-P1-08）。
  const ingestUrl = `${window.location.origin}${created?.ingestPath ?? ''}`

  if (created !== null) {
    return (
      <Dialog
        open
        onClose={onClose}
        title="连接器已创建"
        footer={
          <Button variant="primary" size="sm" onClick={onClose}>
            完成
          </Button>
        }
      >
        <div className="flex flex-col gap-3 text-sm">
          <p className="text-[var(--lumi-text-secondary)]">
            以下凭据<strong className="text-[var(--lumi-text-primary)]">仅显示这一次</strong>
            ，关闭后无法再查看；请立即保存到你的推送脚本中。
          </p>
          <CopyField label="摄取地址（POST，完整 URL）" value={ingestUrl} onCopy={copy} mono />
          <CopyField label="Bearer Secret" value={created.secret} onCopy={copy} mono />
          <p className="text-xs text-[var(--lumi-text-tertiary)]">
            推送示例：curl -X POST {ingestUrl} -H "Authorization: Bearer
            &lt;secret&gt;" -H "Content-Type: application/json" -d
            '{"{"}"guid":"demo-1","title":"第一条","content":"正文"{"}"}'
          </p>
        </div>
      </Dialog>
    )
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title="新建收件连接器"
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
              create.mutate(name.trim(), { onSuccess: setCreated })
            }}
          >
            {create.isPending ? '创建中…' : '创建'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">连接器名称</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="例如：剪藏助手、n8n、我的脚本"
            aria-label="连接器名称"
            className={cx(
              'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
              'px-3 py-2 text-sm text-[var(--lumi-text-primary)]',
              'placeholder:text-[var(--lumi-text-tertiary)]',
              'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
            )}
          />
        </label>
        {create.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {create.error instanceof Error ? create.error.message : '创建失败，请稍后重试。'}
          </p>
        )}
      </div>
    </Dialog>
  )
}

/** 只读凭据行 + 复制按钮（clipboard 失败静默——值仍在框内可手动复制）。 */
function CopyField({
  label,
  value,
  onCopy,
  mono = false,
}: {
  label: string
  value: string
  onCopy: (value: string) => void
  mono?: boolean
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-[var(--lumi-text-secondary)]">{label}</span>
      <span className="flex items-center gap-1">
        <input
          type="text"
          readOnly
          value={value}
          aria-label={label}
          className={cx(
            'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2 text-xs text-[var(--lumi-text-primary)]',
            mono && 'font-mono',
            'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
          )}
        />
        <IconButton
          icon={<Copy aria-hidden className="size-4" />}
          label={`复制${label}`}
          size="sm"
          touch
          onClick={() => onCopy(value)}
        />
      </span>
    </label>
  )
}

/** 连接器列表（名称 + 最近错误 + 两步确认删除）。
 * 删除会级联销毁该连接器的全部推送条目（Q-P2-22）——单击 Trash2 直接
 * mutate 的旧语义破坏半径远大于单条内容，先武装确认再执行。 */
function ConnectorList() {
  const sources = useInboxSources()
  const del = useDeleteInboxSourceMutation()
  const [confirmUuid, setConfirmUuid] = useState<string | null>(null)

  if (sources.isPending) {
    return <Skeleton className="h-10 w-full" />
  }
  if (sources.isError) {
    return (
      <p role="alert" className="text-xs text-[var(--lumi-danger)]">
        连接器加载失败：{sources.error instanceof Error ? sources.error.message : '请稍后重试。'}
      </p>
    )
  }
  if (sources.data.length === 0) {
    return (
      <p className="text-xs text-[var(--lumi-text-tertiary)]">还没有连接器。</p>
    )
  }
  return (
    <ul className="flex flex-col gap-1.5" aria-label="收件连接器列表">
      {sources.data.map((source) => {
        const armed = confirmUuid === source.uuid
        return (
          <li
            key={source.uuid}
            className="flex items-center gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2"
          >
            <span
              aria-hidden
              className={cx(
                'size-1.5 shrink-0 rounded-full',
                source.lastError == null
                  ? 'bg-[var(--lumi-success)]'
                  : 'bg-[var(--lumi-danger)]',
              )}
            />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm text-[var(--lumi-text-primary)]">
                {source.name}
              </span>
              {source.lastError !== null && (
                <span role="alert" className="block truncate text-xs text-[var(--lumi-danger)]">
                  最近错误：{source.lastError}
                </span>
              )}
            </span>
            {armed ? (
              <>
                <Button
                  variant="danger"
                  size="sm"
                  disabled={del.isPending}
                  onClick={() =>
                    del.mutate(source.uuid, { onSettled: () => setConfirmUuid(null) })
                  }
                >
                  {del.isPending && del.variables === source.uuid
                    ? '删除中…'
                    : '确认删除（连同全部条目）'}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={del.isPending}
                  onClick={() => setConfirmUuid(null)}
                >
                  取消
                </Button>
              </>
            ) : (
              <IconButton
                icon={<Trash2 aria-hidden className="size-4" />}
                label={`删除连接器 ${source.name}`}
                size="sm"
                touch
                disabled={del.isPending}
                onClick={() => setConfirmUuid(source.uuid)}
              />
            )}
          </li>
        )
      })}
    </ul>
  )
}

/** 单条收件卡片：统一卡片 + 加入稍后读 / 删除动作。
 *
 * 解析走 per-card useResolveRefs([itemRef])（fresh-eyes Issue 1）：ref
 * 即稳定缓存键——页级批量 key 会随 refs 集合漂移（删除/翻页触发全量
 * 重解析 + 整页 skeleton 闪烁，比原先每卡片 1 请求更糟）。单 ref 请求
 * 被 TanStack 按 key 稳定缓存，30s 内零重发。 */
function InboxCard({ itemRef }: { itemRef: string }) {
  const resolved = useResolveRefs([itemRef])
  const del = useDeleteInboxItemMutation()
  const addReadLater = useAddWorkspaceItemMutation()

  const card = resolved.data?.items.find((candidate) => candidate.ref === itemRef) ?? null
  const stale = card?.stale ?? false

  if (resolved.isPending) {
    return <li><Skeleton className="h-20 w-full" /></li>
  }
  if (card === null) {
    return (
      <li>
        <div role="alert" className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3.5 text-sm text-[var(--lumi-text-secondary)]">
          条目解析失败。
          <Button variant="secondary" size="sm" className="ml-2" onClick={() => resolved.refetch()}>
            重试
          </Button>
        </div>
      </li>
    )
  }
  return (
    <li data-inbox-ref={itemRef}>
      <UnifiedContentCard
        item={card}
        actions={
          <>
            {!stale && (
              <IconButton
                icon={
                  addReadLater.isPending ? (
                    <Loader2 aria-hidden className="size-4 animate-spin" />
                  ) : (
                    <InboxIcon aria-hidden className="size-4" />
                  )
                }
                label="加入稍后读"
                title="加入稍后读"
                size="sm"
                touch
                disabled={addReadLater.isPending}
                onClick={() =>
                  addReadLater.mutate({
                    workspaceId: READ_LATER_WORKSPACE_ID,
                    itemRef,
                  })
                }
              />
            )}
            <IconButton
              icon={
                del.isPending ? (
                  <Loader2 aria-hidden className="size-4 animate-spin" />
                ) : (
                  <Trash2 aria-hidden className="size-4" />
                )
              }
              label="删除收件条目"
              size="sm"
              touch
              disabled={del.isPending}
              onClick={() => del.mutate(itemRef)}
            />
          </>
        }
      />
      {(addReadLater.isError || del.isError || stale) && (
        <div className="mt-1 flex flex-col gap-0.5 text-xs">
          {stale && (
            <span className="text-[var(--lumi-text-tertiary)]">该条目已失效，建议移除。</span>
          )}
          {addReadLater.isError && (
            <span role="alert" className="text-[var(--lumi-danger)]">
              加入稍后读失败：{addReadLater.error instanceof Error ? addReadLater.error.message : '请稍后重试。'}
            </span>
          )}
          {del.isError && (
            <span role="alert" className="text-[var(--lumi-danger)]">
              删除失败：{del.error instanceof Error ? del.error.message : '请稍后重试。'}
            </span>
          )}
        </div>
      )}
    </li>
  )
}

export default function InboxPage() {
  const [createOpen, setCreateOpen] = useState(false)
  const items = useInboxItems()
  const {
    data,
    isPending,
    isError,
    error,
    refetch,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = items

  const refs = useMemo(
    () => data?.pages.flatMap((page) => page.items.map((row) => row.ref)) ?? [],
    [data],
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-3 max-lg:pb-[76px]">
        {/* 头部：标题 + 连接器管理 */}
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-base font-semibold text-[var(--lumi-text-primary)]">收件箱</h1>
          <div className="ml-auto flex items-center gap-1.5">
            <Button variant="primary" size="sm" onClick={() => setCreateOpen(true)}>
              <Plus aria-hidden className="size-4" />
              新建连接器
            </Button>
          </div>
        </div>

        <div className="mt-2">
          <ConnectorList />
        </div>

        {/* 条目 / 诚实状态 */}
        {isPending ? (
          <ul className="mt-3 flex flex-col gap-2" aria-label="收件条目加载中">
            {Array.from({ length: 3 }, (_, i) => (
              <li key={i}>
                <Skeleton className="h-20 w-full" />
              </li>
            ))}
          </ul>
        ) : isError ? (
          <div className="mt-6" role="alert">
            <EmptyState
              icon={<InboxIcon aria-hidden className="size-8" />}
              title="收件条目加载失败"
              description={error instanceof Error ? error.message : '请稍后重试。'}
            />
            <div className="flex justify-center">
              <Button variant="secondary" size="sm" onClick={() => refetch()}>
                重试
              </Button>
            </div>
          </div>
        ) : refs.length === 0 ? (
          <div className="mt-8">
            <EmptyState
              icon={<InboxIcon aria-hidden className="size-8" />}
              title="收件箱为空"
              description="创建连接器后，用任意脚本向摄取地址 POST JSON，内容就会出现在这里，并可被统一搜索找到。"
            />
          </div>
        ) : (
          <>
            <ul className="mt-3 flex flex-col gap-2" aria-label="收件条目列表">
              {refs.map((ref) => (
                <InboxCard key={ref} itemRef={ref} />
              ))}
            </ul>
            {hasNextPage && (
              <div className="mt-3 flex justify-center">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => fetchNextPage()}
                  disabled={isFetchingNextPage}
                >
                  {isFetchingNextPage ? '加载中…' : '加载更多'}
                </Button>
              </div>
            )}
          </>
        )}
      </div>
      {createOpen && <CreateConnectorDialog onClose={() => setCreateOpen(false)} />}
    </div>
  )
}
