/** ApiSourcesSection — phase2 G6：设置 → API 来源。
 *
 * 非 RSS JSON API → JMESPath → Atom 的来源管理：
 * - 列表：名称 / endpoint host / 启用开关（PATCH）/ lastStatus 徽标
 *   （ok=正常、fetch_failed=错误（tooltip lastError）、subscribe_failed）
 *   / lastSuccessAt 相对时间；删除立即生效（服务端自动退订）。
 * - 新增流程（Dialog）：名称 / Endpoint / items 表达式 / fieldMap 五键
 *   + 预览（POST preview，≤5 条映射结果语义表格；错误 message 原样透出）
 *   + 保存（POST）；创建响应是唯一一次包含 atomPath 的机会——一次性
 *   成功面板 + 复制按钮 + 「仅显示一次」说明；subscribeError 诚实展示。
 *
 * 所有 HTTP 经 src/api/client.ts（本组件零 fetch）；状态全部来自
 * TanStack Query（loading / empty / error 三态齐备）。 */

import { useState } from 'react'
import { AlertCircle, CheckCircle2, ChevronDown, Copy, Plus, RefreshCw, Trash2 } from 'lucide-react'
import {
  useApiSourcePreviewMutation,
  useApiSources,
  useCreateApiSourceMutation,
  useDeleteApiSourceMutation,
  useUpdateApiSourceMutation,
} from '../../api/queries'
import type {
  ApiSource,
  ApiSourcePaginationInput,
  ApiSourcePreviewResult,
} from '../../api/client'
import { confirmApiSourceSchema } from '../../api/client'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { dateTimeFormatter } from '../../lib/date-format'
import { Button } from '../ui/Button'
import { Dialog } from '../ui/Dialog'
import { EmptyState } from '../ui/EmptyState'
import { IconButton } from '../ui/IconButton'
import { Skeleton } from '../ui/Skeleton'
import { Switch } from '../ui/Switch'
import { cx } from '../ui/cx'

/** ISO 时间戳 → 相对时间；缺失 / 无效 / 超过 30 天回退绝对时间。 */
function formatRelative(iso: string | null | undefined): string {
  if (iso === null || iso === undefined || iso === '') return '从未'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '从未'
  const minutes = Math.floor((Date.now() - date.getTime()) / 60_000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return dateTimeFormatter.format(date)
}

/** endpoint → host（malformed 原样展示，不吞 URL）。 */
function endpointHost(endpoint: string): string {
  try {
    return new URL(endpoint).host
  } catch {
    return endpoint
  }
}

function copyText(text: string): void {
  void navigator.clipboard?.writeText(text)
}

/** lastStatus 徽标：ok=正常（绿系 token）；fetch_failed=错误（tooltip
 * lastError）；subscribe_failed=订阅失败；其余=未运行。 */
function StatusBadge({ source }: { source: ApiSource }) {
  const status = source.lastStatus ?? null
  if (status === 'ok') {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-[var(--lumi-category-green)]">
        <CheckCircle2 aria-hidden className="size-3.5" />
        正常
      </span>
    )
  }
  if (status === 'fetch_failed' || status === 'subscribe_failed') {
    const detail =
      status === 'subscribe_failed'
        ? (source.subscribeError ?? source.lastError)
        : source.lastError
    return (
      <span
        title={detail ?? undefined}
        className="inline-flex cursor-help items-center gap-1 text-xs font-medium text-[var(--lumi-danger)]"
      >
        <AlertCircle aria-hidden className="size-3.5" />
        {status === 'fetch_failed' ? '错误' : '订阅失败'}
      </span>
    )
  }
  return <span className="text-xs text-[var(--lumi-text-tertiary)]">未运行</span>
}

const inputCls = cx(
  'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 min-h-9 text-sm',
  'text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)]',
  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
  'disabled:cursor-not-allowed disabled:opacity-50',
)

const FIELD_MAP_FIELDS: { key: keyof ApiSourceFieldMapState; label: string }[] = [
  { key: 'id', label: 'id 表达式' },
  { key: 'title', label: 'title 表达式' },
  { key: 'url', label: 'url 表达式' },
  { key: 'published', label: 'published 表达式' },
  { key: 'body', label: 'body 表达式' },
]

interface ApiSourceFieldMapState {
  id: string
  title: string
  url: string
  published: string
  body: string
}

const EMPTY_FIELD_MAP: ApiSourceFieldMapState = {
  id: '',
  title: '',
  url: '',
  published: '',
  body: '',
}

/** 语义预览表格：≤5 条映射结果（列 = fieldMap 已填的键）。 */
function PreviewTable({ preview }: { preview: ApiSourcePreviewResult }) {
  const columns = FIELD_MAP_FIELDS.map((f) => f.key)
  return (
    <div className="mt-1">
      <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
        预览成功：共约 {preview.totalAvailable} 条，以下为前 {preview.items.length} 条映射结果。
      </p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full border-collapse text-left text-xs">
          <thead>
            <tr>
              {columns.map((col) => (
                <th
                  key={col}
                  scope="col"
                  className="border-b border-[var(--lumi-separator)] px-2 py-1.5 font-medium text-[var(--lumi-text-tertiary)]"
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview.items.map((item, i) => (
              <tr key={i}>
                {columns.map((col) => {
                  const value = item[col]
                  return (
                    <td
                      key={col}
                      className="max-w-40 truncate border-b border-[var(--lumi-separator)] px-2 py-1.5 text-[var(--lumi-text-secondary)]"
                    >
                      {value === undefined || value === null ? '—' : String(value)}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/** F042：分页采样配置块 —— mode/参数 + dry-run 按钮 + {pages, stopReason} 结果。 */
const STOP_REASON_LABELS: Record<string, string> = {
  single: '单次抓取',
  empty_page: '空页停止',
  cursor_missing: '游标缺失停止',
  cursor_repeat: '游标重复停止',
  max_pages: '达到页数上限',
  max_items: '达到条数上限',
}

function PaginationConfigBlock({
  value,
  onChange,
  dryRun,
  dryRunPending,
  dryRunError,
  onDryRun,
  canDryRun,
}: {
  value: ApiSourcePaginationInput
  onChange: (next: ApiSourcePaginationInput) => void
  dryRun: ApiSourcePreviewResult | null
  dryRunPending: boolean
  dryRunError: string | null
  onDryRun: () => void
  canDryRun: boolean
}) {
  const inputCls =
    'w-24 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs text-[var(--lumi-text-primary)]'
  return (
    <fieldset className="mt-3 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3">
      <legend className="px-1 text-xs font-medium text-[var(--lumi-text-primary)]">
        分页采样（F042）
      </legend>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]">
          模式
          <select
            aria-label="分页模式"
            value={value.mode}
            onChange={(e) => {
              const mode = e.target.value as ApiSourcePaginationInput['mode']
              onChange({ mode, ...(mode === 'none' ? {} : { max_pages: 5, max_items: 200 }) })
            }}
            className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs text-[var(--lumi-text-primary)]"
          >
            <option value="none">不分页</option>
            <option value="page">页码 ?page=N</option>
            <option value="cursor">游标 ?cursor=</option>
          </select>
        </label>
        {value.mode === 'page' && (
          <>
            <label className="flex items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]">
              页参数名
              <input
                aria-label="页参数名"
                value={value.page_param ?? ''}
                onChange={(e) => onChange({ ...value, page_param: e.target.value })}
                className={inputCls}
                placeholder="page"
              />
            </label>
            <label className="flex items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]">
              起始页
              <input
                aria-label="起始页"
                type="number"
                min={1}
                value={value.first_page ?? 1}
                onChange={(e) =>
                  onChange({ ...value, first_page: Math.max(1, Number(e.target.value) || 1) })
                }
                className={inputCls}
              />
            </label>
          </>
        )}
        {value.mode === 'cursor' && (
          <label className="flex items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]">
            游标路径（JMESPath）
            <input
              aria-label="游标路径"
              value={value.cursor_path ?? ''}
              onChange={(e) => onChange({ ...value, cursor_path: e.target.value })}
              className={inputCls}
              placeholder="meta.next"
            />
          </label>
        )}
        {value.mode !== 'none' && (
          <>
            <label className="flex items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]">
              最多页数
              <input
                aria-label="最多页数"
                type="number"
                min={1}
                max={50}
                value={value.max_pages ?? 5}
                onChange={(e) => onChange({ ...value, max_pages: Number(e.target.value) || 5 })}
                className={inputCls}
              />
            </label>
            <label className="flex items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]">
              最多条数
              <input
                aria-label="最多条数"
                type="number"
                min={1}
                max={1000}
                value={value.max_items ?? 200}
                onChange={(e) => onChange({ ...value, max_items: Number(e.target.value) || 200 })}
                className={inputCls}
              />
            </label>
            <Button
              size="sm"
              variant="ghost"
              onClick={onDryRun}
              disabled={!canDryRun || dryRunPending}
            >
              <RefreshCw aria-hidden className="size-3.5" />
              {dryRunPending ? '试跑中…' : '分页试跑'}
            </Button>
          </>
        )}
      </div>
      {value.mode !== 'none' && (
        <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]">
          中途失败（如 429/超时）时本次不发布任何条目；空页、游标缺失或重复、达到上限则如实停止。
        </p>
      )}
      {dryRunError !== null && (
        <p role="alert" className="mt-1.5 text-xs text-[var(--lumi-danger)]">
          {dryRunError}
        </p>
      )}
      {dryRun?.paginationDryRun != null && (
        <div className="mt-2 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-hover)] p-2 text-xs">
          <p className="font-medium text-[var(--lumi-text-primary)]">
            试跑：{dryRun.paginationDryRun.pages.length} 页 ·{' '}
            {STOP_REASON_LABELS[dryRun.paginationDryRun.stopReason] ??
              dryRun.paginationDryRun.stopReason}{' '}
            · 共约 {dryRun.totalAvailable} 条
          </p>
          <p className="mt-0.5 text-[var(--lumi-text-tertiary)]">
            {dryRun.paginationDryRun.pages
              .map((p) => `第 ${String(p.index)} 页 ${String(p.mappedItems)} 条`)
              .join('，')}
          </p>
        </div>
      )}
    </fieldset>
  )
}

/** F041：Atom 预览折叠区 —— 前 ≤3 条 entry 的最终形态（urn id / RFC3339 /
 * 链接 / 内容摘要），与 FreshRSS 实际摄取的渲染管线一致。 */
function AtomPreviewSection({ preview }: { preview: ApiSourcePreviewResult }) {
  const [open, setOpen] = useState(false)
  if (preview.atomPreview.length === 0) return null
  return (
    <div className="mt-3">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-[var(--lumi-radius-md)] px-2 py-1 text-xs font-medium text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]"
      >
        <ChevronDown
          aria-hidden
          className={cx('size-3.5 transition-transform duration-[var(--lumi-motion-fast)]', open && 'rotate-180')}
        />
        Atom 预览（前 {preview.atomPreview.length} 条最终形态）
      </button>
      {open && (
        <dl className="mt-2 flex flex-col gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3">
          {preview.atomPreview.map((entry) => (
            <div key={String(entry.id)} className="flex flex-col gap-0.5">
              <dt className="truncate text-xs font-medium text-[var(--lumi-text-primary)]">
                {String(entry.title)}
              </dt>
              <dd className="font-mono text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]">
                id {String(entry.id)}
                {entry.published ? ` · ${String(entry.published)}` : ''}
              </dd>
              {entry.link !== null && entry.link !== undefined && (
                <dd className="truncate text-[11px] text-[var(--lumi-text-secondary)]">
                  {String(entry.link)}
                </dd>
              )}
              {typeof entry.contentExcerpt === 'string' && entry.contentExcerpt !== '' && (
                <dd className="line-clamp-2 text-[11px] leading-relaxed text-[var(--lumi-text-secondary)]">
                  {entry.contentExcerpt}
                </dd>
              )}
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}

/** 新增流程：表单 + 预览 + 保存；成功后切换为一次性 atomPath 面板。 */
function CreateApiSourceDialog({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const [name, setName] = useState('')
  const [endpoint, setEndpoint] = useState('')
  const [itemsExpr, setItemsExpr] = useState('')
  const [fieldMap, setFieldMap] = useState<ApiSourceFieldMapState>(EMPTY_FIELD_MAP)
  const [pagination, setPagination] = useState<ApiSourcePaginationInput>({ mode: 'none' })
  const [preview, setPreview] = useState<ApiSourcePreviewResult | null>(null)
  const [created, setCreated] = useState<ApiSource | null>(null)

  const createMutation = useCreateApiSourceMutation()
  const previewMutation = useApiSourcePreviewMutation()

  const canSave = name.trim() !== '' && endpoint.trim() !== '' && itemsExpr.trim() !== ''
  const canPreview = endpoint.trim() !== '' && itemsExpr.trim() !== ''

  const reset = () => {
    setName('')
    setEndpoint('')
    setItemsExpr('')
    setFieldMap(EMPTY_FIELD_MAP)
    setPagination({ mode: 'none' })
    setPreview(null)
    setCreated(null)
    createMutation.reset()
    previewMutation.reset()
  }

  const close = () => {
    onClose()
    // 关闭即重置：atomPath 一次性语义不允许「重开还能看到旧 secret」。
    reset()
  }

  const runPreview = () => {
    previewMutation.mutate(
      {
        endpoint: endpoint.trim(),
        itemsExpr: itemsExpr.trim(),
        fieldMap: { ...fieldMap },
      },
      { onSuccess: (result) => setPreview(result) },
    )
  }

  // F042：分页 dry-run（对样本响应走页，不入库）
  const [dryRun, setDryRun] = useState<ApiSourcePreviewResult | null>(null)
  const dryRunMutation = useApiSourcePreviewMutation()
  const runDryRun = () => {
    dryRunMutation.mutate(
      {
        endpoint: endpoint.trim(),
        itemsExpr: itemsExpr.trim(),
        fieldMap: { ...fieldMap },
        pagination: { ...pagination },
        dryRunPagination: true,
      },
      { onSuccess: (result) => setDryRun(result) },
    )
  }

  const save = () => {
    createMutation.mutate(
      {
        name: name.trim(),
        endpoint: endpoint.trim(),
        itemsExpr: itemsExpr.trim(),
        fieldMap: { ...fieldMap },
        pagination: { ...pagination },
      },
      { onSuccess: (source) => setCreated(source) },
    )
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      title={created !== null ? 'API 来源已创建' : '新增 API 来源'}
      footer={
        created !== null ? (
          <Button variant="primary" size="sm" onClick={close}>
            完成
          </Button>
        ) : (
          <>
            <Button variant="ghost" size="sm" onClick={close}>
              取消
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={save}
              disabled={!canSave || createMutation.isPending}
            >
              {createMutation.isPending ? '保存中…' : '保存'}
            </Button>
          </>
        )
      }
    >
      {created !== null ? (
        // 一次性成功面板：atomPath 只在创建响应里出现，刷新即丢失。
        <div role="status" className="flex flex-col gap-3">
          <p className="flex items-center gap-1.5 text-sm font-medium text-[var(--lumi-text-primary)]">
            <CheckCircle2 aria-hidden className="size-4 text-[var(--lumi-category-green)]" />
            已创建「{created.name}」
          </p>
          <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3">
            <p className="text-xs font-medium text-[var(--lumi-text-primary)]">Atom 订阅地址</p>
            <div className="mt-1.5 flex items-center gap-1.5">
              <code className="min-w-0 flex-1 truncate rounded-[var(--lumi-radius-sm)] bg-[var(--lumi-surface-selected)] px-2 py-1 font-mono text-xs text-[var(--lumi-text-primary)]">
                {created.atomPath ?? '（服务端未返回地址）'}
              </code>
              {created.atomPath != null && created.atomPath !== '' && (
                <IconButton
                  icon={<Copy aria-hidden className="size-3.5" />}
                  label="复制"
                  title="复制 Atom 订阅地址"
                  size="sm"
                  onClick={() => copyText(created.atomPath ?? '')}
                />
              )}
            </div>
            <p className="mt-2 text-xs leading-relaxed text-[var(--lumi-danger)]">
              此地址仅显示一次，请立即粘贴到 FreshRSS 订阅；关闭后无法再次查看。
            </p>
          </div>
          {created.subscribeError != null && created.subscribeError !== '' && (
            <p role="alert" className="flex items-start gap-1.5 text-xs leading-relaxed text-[var(--lumi-danger)]">
              <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
              自动订阅 FreshRSS 失败：{created.subscribeError}
            </p>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <label htmlFor="api-source-name" className="block text-xs font-medium text-[var(--lumi-text-primary)]">
            名称
          </label>
          <input
            id="api-source-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="例如：Hacker News"
            className={inputCls}
          />
          <label htmlFor="api-source-endpoint" className="block text-xs font-medium text-[var(--lumi-text-primary)]">
            Endpoint
          </label>
          <input
            id="api-source-endpoint"
            type="url"
            value={endpoint}
            onChange={(e) => setEndpoint(e.target.value)}
            placeholder="https://api.example.com/v1/items"
            className={inputCls}
          />
          <label htmlFor="api-source-items" className="block text-xs font-medium text-[var(--lumi-text-primary)]">
            items 表达式（JMESPath）
          </label>
          <input
            id="api-source-items"
            value={itemsExpr}
            onChange={(e) => setItemsExpr(e.target.value)}
            placeholder="例如：items"
            className={inputCls}
          />
          <fieldset className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3">
            <legend className="px-1 text-xs font-medium text-[var(--lumi-text-primary)]">
              字段映射（fieldMap → JMESPath）
            </legend>
            <div className="mt-1 flex flex-col gap-2">
              {FIELD_MAP_FIELDS.map((field) => (
                <div key={field.key} className="flex items-center gap-2">
                  <label
                    htmlFor={`api-source-field-${field.key}`}
                    className="w-20 shrink-0 text-xs text-[var(--lumi-text-secondary)]"
                  >
                    {field.label}
                  </label>
                  <input
                    id={`api-source-field-${field.key}`}
                    value={fieldMap[field.key]}
                    onChange={(e) =>
                      setFieldMap((prev) => ({ ...prev, [field.key]: e.target.value }))
                    }
                    className={cx(inputCls, 'min-h-8 flex-1')}
                  />
                </div>
              ))}
            </div>
          </fieldset>

          <PaginationConfigBlock
            value={pagination}
            onChange={setPagination}
            dryRun={dryRun}
            dryRunPending={dryRunMutation.isPending}
            dryRunError={dryRunMutation.error instanceof Error ? dryRunMutation.error.message : null}
            onDryRun={runDryRun}
            canDryRun={canPreview}
          />

          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={runPreview}
              disabled={!canPreview || previewMutation.isPending}
            >
              <RefreshCw aria-hidden className="size-3.5" />
              {previewMutation.isPending ? '预览中…' : '预览'}
            </Button>
          </div>
          {previewMutation.isError && (
            <p role="alert" className="flex items-start gap-1.5 text-xs leading-relaxed text-[var(--lumi-danger)]">
              <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
              {previewMutation.error.message}
            </p>
          )}
          {preview !== null && !previewMutation.isError && (
            <>
              <PreviewTable preview={preview} />
              <AtomPreviewSection preview={preview} />
            </>
          )}
          {createMutation.isError && (
            <p role="alert" className="flex items-start gap-1.5 text-xs leading-relaxed text-[var(--lumi-danger)]">
              <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
              {createMutation.error.message}
            </p>
          )}
        </div>
      )}
    </Dialog>
  )
}

/** F043：结构漂移徽标 + 「数据结构」面板（基线 vs 当前 diff + 重新确认）。 */
function SchemaDriftPanel({ source }: { source: ApiSource }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const confirm = useMutation({
    mutationFn: () => confirmApiSourceSchema(source.uuid),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['api-sources'] })
    },
  })
  const drift = source.schemaDrift
  const hasDrift =
    drift !== null && drift !== undefined && (drift.missing.length > 0 || drift.type_changed.length > 0)
  if (!source.confirmedSchema && !hasDrift) return null
  return (
    <div className="mt-1.5">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-[var(--lumi-radius-md)] px-1.5 py-0.5 text-[11px] text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]"
      >
        <ChevronDown
          aria-hidden
          className={cx('size-3 transition-transform duration-[var(--lumi-motion-fast)]', open && 'rotate-180')}
        />
        数据结构
        {hasDrift ? (
          <span className="flex items-center gap-1 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-danger-soft,rgba(220,80,80,0.15))] px-1.5 py-0.5 text-[10px] text-[var(--lumi-danger)]">
            <AlertCircle aria-hidden className="size-3" />
            结构已变化
          </span>
        ) : (
          <span className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-text-tertiary)]">
            基线已确认
          </span>
        )}
      </button>
      {open && (
        <div className="mt-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2.5 text-xs">
          {!source.confirmedSchema && (
            <p className="text-[var(--lumi-text-tertiary)]">尚未确认结构基线。</p>
          )}
          {source.confirmedSchema && !hasDrift && (
            <p className="text-[var(--lumi-text-secondary)]">
              当前数据与确认基线一致（可选新增字段：
              {drift?.new_optional.length ?? 0}）。
            </p>
          )}
          {hasDrift && (
            <div className="flex flex-col gap-1 text-[var(--lumi-text-secondary)]">
              {(drift?.missing.length ?? 0) > 0 && (
                <p>
                  缺失必需字段：
                  <span className="font-mono text-[var(--lumi-danger)]">{drift?.missing.join('、')}</span>
                </p>
              )}
              {(drift?.type_changed.length ?? 0) > 0 && (
                <p>
                  类型变化：
                  <span className="font-mono text-[var(--lumi-danger)]">{drift?.type_changed.join('、')}</span>
                </p>
              )}
              {(drift?.new_optional.length ?? 0) > 0 && (
                <p className="text-[var(--lumi-text-tertiary)]">
                  新增可选字段（仅提示）：{drift?.new_optional.join('、')}
                </p>
              )}
            </div>
          )}
          <div className="mt-2 flex items-center gap-2">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => confirm.mutate()}
              disabled={confirm.isPending}
            >
              <RefreshCw aria-hidden className="size-3.5" />
              {confirm.isPending ? '确认中…' : '修订映射并重新确认'}
            </Button>
            {confirm.isError && (
              <span role="alert" className="text-[var(--lumi-danger)]">
                {confirm.error instanceof Error ? confirm.error.message : '确认失败'}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

/** 单行：名称 + host + 状态徽标 + 上次成功相对时间 + 启用开关 + 删除。 */
function ApiSourceRow({ source }: { source: ApiSource }) {
  const update = useUpdateApiSourceMutation()
  const remove = useDeleteApiSourceMutation()
  return (
    <li className="flex items-center gap-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-3 py-2.5">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-[var(--lumi-text-primary)]">{source.name}</p>
        <p className="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-[var(--lumi-text-tertiary)]">
          <span className="truncate">{endpointHost(source.endpoint)}</span>
          <StatusBadge source={source} />
          <span>上次成功：{formatRelative(source.lastSuccessAt)}</span>
        </p>
        <SchemaDriftPanel source={source} />
        {/* P0-05f：409 unsubscribe_failed —— FreshRSS 退订失败时服务端
            保留来源（防止死订阅继续轮询），这里诚实透出原因 + 重试提示，
            不假装删除成功。 */}
        {remove.isError && (
          <p role="alert" className="mt-1 text-xs leading-relaxed text-[var(--lumi-danger)]">
            删除失败，来源已保留（可重试）：{remove.error instanceof Error ? remove.error.message : '请稍后重试。'}
          </p>
        )}
      </div>
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
    </li>
  )
}

export function ApiSourcesSection() {
  const sources = useApiSources()
  const [createOpen, setCreateOpen] = useState(false)

  return (
    <div className="flex flex-col gap-3 py-1">
      <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        把任意 JSON API 变成 Atom 订阅：用 JMESPath 描述列表与字段，Lumi 生成
        Atom 地址供 FreshRSS 订阅。
      </p>
      <div>
        <Button size="sm" variant="secondary" onClick={() => setCreateOpen(true)}>
          <Plus aria-hidden className="size-3.5" />
          新增来源
        </Button>
      </div>

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

      {sources.isSuccess && sources.data.items.length === 0 && (
        <EmptyState
          icon={<Plus aria-hidden className="size-8" />}
          title="还没有 API 来源"
          description="填入一个 JSON API 的地址与字段映射，即可生成 Atom 订阅。"
        />
      )}

      {sources.isSuccess && sources.data.items.length > 0 && (
        <ul className="flex flex-col gap-2" aria-label="API 来源列表">
          {sources.data.items.map((source) => (
            <ApiSourceRow key={source.uuid} source={source} />
          ))}
        </ul>
      )}

      <CreateApiSourceDialog open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  )
}
