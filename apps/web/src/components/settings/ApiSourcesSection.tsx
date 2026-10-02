/** ApiSourcesSection — 设置 → API 来源。
 *
 * 空态治理（R12）：没有任何 API 来源时只显示一句说明 + 「添加 API
 * 来源」主按钮 + 可折叠的「了解支持的 API」帮助；全部高级接入工具
 * （字段映射 / 分页试抓 / Webhook 收发 / 轮换 / 转移等）不可见。
 *
 * 有 ≥1 个来源后：
 * - 列表行：名称 / host / 状态徽标 / 更新频率 / 最近抓取或错误；
 *   行点击打开 ApiSourceDetailDrawer（内容 / 抓取 / 字段 / 日志 /
 *   高级 五个 tab）；启用开关与删除仍在行内（删除失败 409 诚实透出）；
 * - 「接入中心」聚合入口出现（默认折叠，展开才发请求）：Webhook
 *   收件箱 / 外发事件订阅 / 投递回执 / 死信重试（仅有失败记录时）。
 *
 * 所有 HTTP 经 src/api/client.ts（本组件零 fetch）；状态全部来自
 * TanStack Query（loading / empty / error 三态齐备）。 */

import { useState, type ReactElement } from 'react'
import { AlertCircle, BookOpen, Plus, Trash2 } from 'lucide-react'
import {
  useApiSources,
  useDeleteApiSourceMutation,
  useUpdateApiSourceMutation,
} from '../../api/queries'
import { endpointHost, formatRelative, StatusBadge } from '../new301/api-source-shared'
import { ApiSourceDetailDrawer } from '../new301/ApiSourceDetailDrawer'
import { CreateApiSourceWizard } from '../new301/CreateApiSourceWizard'
import { IntakeCenter } from '../new301/New301IntakeTools'
import type { ApiSource } from '../../api/client'
import { SubSection } from '../new271/panel'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { IconButton } from '../ui/IconButton'
import { Skeleton } from '../ui/Skeleton'
import { Switch } from '../ui/Switch'

/** 空态帮助（次级、可折叠）：支持范围说明。 */
function EmptyStateHelp(): ReactElement {
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-1 flex flex-col items-center">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex min-h-11 items-center gap-1.5 rounded-[var(--lumi-radius-md)] px-2 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]"
        data-empty-help-toggle=""
      >
        <BookOpen aria-hidden className="size-3.5" />
        了解支持的 API
      </button>
      {open && (
        <div className="mt-1 max-w-md rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3 text-xs leading-relaxed text-[var(--lumi-text-secondary)]" data-empty-help-panel="">
          <p>任何返回 JSON 列表的 HTTP API 都能接入：描述列表位置与字段，生成 Atom 订阅地址。</p>
          <p className="mt-1.5">支持页码与游标分页和每日条目上限；上游结构变化会预警并暂停写入。</p>
          <p className="mt-1.5">抓取由服务端定时执行；内网地址会被拒绝，凭据只存服务端、界面不回显。</p>
        </div>
      )}
    </div>
  )
}

/** 单行：名称 + host + 状态 + 更新频率 + 最近抓取或错误；点击开详情。
 * 行内控件：启用开关 + 删除（409 退订失败时来源保留、原因诚实透出）。 */
function ApiSourceRow({
  source,
  onOpen,
}: {
  source: ApiSource
  onOpen: (uuid: string) => void
}) {
  const update = useUpdateApiSourceMutation()
  const remove = useDeleteApiSourceMutation()
  return (
    <li className="flex items-center gap-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-3 py-2.5">
      <div className="min-w-0 flex-1">
        <button
          type="button"
          onClick={() => onOpen(source.uuid)}
          aria-label={`查看 ${source.name} 详情`}
          data-source-row={source.uuid}
          className="w-full rounded-[var(--lumi-radius-md)] py-1 text-left transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        >
          <span className="block truncate text-sm font-medium text-[var(--lumi-text-primary)]">{source.name}</span>
          <span className="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-[var(--lumi-text-tertiary)]">
            <span className="truncate">{endpointHost(source.endpoint)}</span>
            <StatusBadge source={source} />
            <span>更新频率 ≤{source.maxRunsPerHour} 次/小时</span>
            <span>
              {source.lastStatus === 'fetch_failed' && source.lastError
                ? `最近抓取失败：${source.lastError}`
                : `最近抓取：${formatRelative(source.lastSuccessAt)}`}
            </span>
          </span>
        </button>
        {/* P0-05f：409 unsubscribe_failed —— FreshRSS 退订失败时服务端
            保留来源（防止死订阅继续轮询），这里诚实透出原因 + 重试提示，
            不假装删除成功。 */}
        {remove.isError && (
          <p role="alert" className="mt-1 text-xs leading-relaxed text-[var(--lumi-danger)]">
            删除失败，来源已保留（可重试）：
            {remove.error instanceof Error ? remove.error.message : '请稍后重试。'}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Switch
          checked={source.enabled}
          label={`启用 ${source.name}`}
          disabled={update.isPending}
          onCheckedChange={(checked) => update.mutate({ uuid: source.uuid, patch: { enabled: checked } })}
        />
        <IconButton
          icon={<Trash2 aria-hidden className="size-4" />}
          label={`删除 ${source.name}`}
          title="删除（自动退订，立即生效）"
          onClick={() => remove.mutate(source.uuid)}
          disabled={remove.isPending}
        />
      </div>
    </li>
  )
}

export function ApiSourcesSection() {
  const sources = useApiSources()
  const [createOpen, setCreateOpen] = useState(false)
  const [detailUuid, setDetailUuid] = useState<string | null>(null)

  const items = sources.isSuccess ? sources.data.items : []
  const detailSource =
    detailUuid !== null ? (items.find((one) => one.uuid === detailUuid) ?? null) : null

  return (
    <div className="flex flex-col gap-3 py-1">
      {sources.isPending && (
        <div className="flex flex-col gap-2" aria-label="API 来源加载中">
          {[0, 1].map((i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      )}

      {sources.isError && (
        <div role="alert" className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3 text-sm">
          <p className="flex items-center gap-1.5 text-[var(--lumi-danger)]">
            <AlertCircle aria-hidden className="size-3.5 shrink-0" />
            API 来源加载失败
          </p>
          <p className="mt-1 text-xs text-[var(--lumi-text-secondary)]">{sources.error.message}</p>
          <Button size="sm" variant="secondary" className="mt-2" onClick={() => sources.refetch()}>
            重试
          </Button>
        </div>
      )}

      {sources.isSuccess && items.length === 0 && (
        <div data-api-sources-empty="">
          <EmptyState
            icon={<Plus aria-hidden className="size-8" />}
            title="还没有 API 来源"
            description="连接 JSON API，自动生成订阅。"
            action={
              <Button variant="primary" size="md" onClick={() => setCreateOpen(true)} data-empty-add="">
                <Plus aria-hidden className="size-4" />
                添加 API 来源
              </Button>
            }
          />
          <EmptyStateHelp />
        </div>
      )}

      {sources.isSuccess && items.length > 0 && (
        <>
          <div>
            <Button size="sm" variant="secondary" onClick={() => setCreateOpen(true)}>
              <Plus aria-hidden className="size-3.5" />
              添加 API 来源
            </Button>
          </div>
          <ul className="flex flex-col gap-2" aria-label="API 来源列表">
            {items.map((source) => (
              <ApiSourceRow key={source.uuid} source={source} onOpen={setDetailUuid} />
            ))}
          </ul>
          {/* 接入中心聚合入口：仅在有来源时出现；折叠态零请求。 */}
          <SubSection id="intake-center-entry" label="接入中心">
            <IntakeCenter />
          </SubSection>
        </>
      )}

      <CreateApiSourceWizard open={createOpen} onClose={() => setCreateOpen(false)} />

      {detailSource !== null && (
        <ApiSourceDetailDrawer
          source={detailSource}
          open={detailUuid !== null && detailSource.uuid === detailUuid}
          onClose={() => setDetailUuid(null)}
        />
      )}
    </div>
  )
}
