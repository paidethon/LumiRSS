/** CreateApiSourceWizard — 分步新增 API 来源。
 *
 * 步骤（任务 R12 规格）：
 * 1 地址与认证 → 2 预览 JSON → 3 字段映射 → 4 有界试抓 → 5 保存并订阅。
 *
 * - 复用既有 preview / preview-sample API；创建响应仍是唯一一次
 *   atomPath/secret 的机会（一次性成功面板 + 复制）；
 * - 预览 / 试抓请求可中止（AbortController，关闭面板即中止）；
 * - 分页有硬上限（≤50 页 / ≤1000 条，后端为准）；防 SSRF 是后端
 *   职责，前端只做提示文案；
 * - 创建契约不含上游凭据字段（ApiSourceCreate 无此键），认证说明
 *   诚实提示「凭据走地址参数、仅存服务端」；write-only 掩码语义
 *   落在来源详情「高级」的凭据轮换输入上。 */

import { useEffect, useMemo, useRef, useState, type ReactElement } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  Copy,
  RefreshCw,
} from 'lucide-react'
import {
  useApiSourcePreviewMutation,
  useApiSourceSamplePreviewMutation,
  useCreateApiSourceMutation,
} from '../../api/queries'
import type {
  ApiSource,
  ApiSourcePaginationInput,
  ApiSourcePreviewResult,
} from '../../api/client'
import {
  parseSampleJson,
  sampleFieldOptions,
  toFieldExpr,
} from '../../lib/api-sample-fields'
import { Button } from '../ui/Button'
import { Dialog } from '../ui/Dialog'
import { IconButton } from '../ui/IconButton'
import { Tabs } from '../ui/Tabs'
import { cx } from '../ui/cx'
import {
  EMPTY_FIELD_MAP,
  FIELD_MAP_FIELDS,
  type ApiSourceFieldMapState,
} from './field-map'

const inputCls = cx(
  'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 min-h-9 text-sm',
  'text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)]',
  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
  'disabled:cursor-not-allowed disabled:opacity-50',
)

const WIZARD_STEPS = [
  '地址与认证',
  '预览 JSON',
  '字段映射',
  '有界试抓',
  '保存并订阅',
] as const

function isAbortError(error: unknown): boolean {
  return (
    error instanceof DOMException &&
    error.name === 'AbortError'
  )
}

function copyText(text: string): void {
  void navigator.clipboard?.writeText(text)
}

/** 步骤指示器：ol + aria-current=step。 */
function StepIndicator({ current }: { current: number }): ReactElement {
  return (
    <ol
      aria-label="新增步骤"
      className="flex flex-wrap items-center gap-x-1 gap-y-1 text-xs text-[var(--lumi-text-tertiary)]"
    >
      {WIZARD_STEPS.map((label, index) => (
        <li
          key={label}
          aria-current={index === current ? 'step' : undefined}
          className={cx(
            'flex items-center gap-1',
            index === current && 'font-medium text-[var(--lumi-text-primary)]',
            index < current && 'text-[var(--lumi-text-secondary)]',
          )}
        >
          {index > 0 && <span aria-hidden="true">›</span>}
          <span>
            {index + 1}. {label}
          </span>
        </li>
      ))}
    </ol>
  )
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

const STOP_REASON_LABELS: Record<string, string> = {
  single: '单次抓取',
  empty_page: '空页停止',
  cursor_missing: '游标缺失停止',
  cursor_repeat: '游标重复停止',
  max_pages: '达到页数上限',
  max_items: '达到条数上限',
}

/** 分页采样配置块（有界）：mode/参数 + dry-run（可中止）+ 结果。 */
function PaginationConfigBlock({
  value,
  onChange,
  dryRun,
  dryRunPending,
  dryRunError,
  dryRunCancelled,
  onDryRun,
  onDryRunCancel,
  canDryRun,
}: {
  value: ApiSourcePaginationInput
  onChange: (next: ApiSourcePaginationInput) => void
  dryRun: ApiSourcePreviewResult | null
  dryRunPending: boolean
  dryRunError: string | null
  dryRunCancelled: boolean
  onDryRun: () => void
  onDryRunCancel: () => void
  canDryRun: boolean
}) {
  const smallInputCls =
    'w-24 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs text-[var(--lumi-text-primary)]'
  return (
    <fieldset className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3">
      <legend className="px-1 text-xs font-medium text-[var(--lumi-text-primary)]">
        分页采样
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
                className={smallInputCls}
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
                className={smallInputCls}
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
              className={smallInputCls}
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
                onChange={(e) =>
                  onChange({ ...value, max_pages: Math.min(50, Math.max(1, Number(e.target.value) || 5)) })
                }
                className={smallInputCls}
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
                onChange={(e) =>
                  onChange({ ...value, max_items: Math.min(1000, Math.max(1, Number(e.target.value) || 200)) })
                }
                className={smallInputCls}
              />
            </label>
            {dryRunPending ? (
              <Button size="sm" variant="ghost" onClick={onDryRunCancel}>
                中止试跑
              </Button>
            ) : (
              <Button
                size="sm"
                variant="ghost"
                onClick={onDryRun}
                disabled={!canDryRun}
              >
                <RefreshCw aria-hidden className="size-3.5" />
                分页试跑
              </Button>
            )}
          </>
        )}
      </div>
      {value.mode !== 'none' && (
        <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]">
          有界试抓：最多 50 页 / 1000 条；中途失败（如 429/超时）时本次不发布任何条目；
          空页、游标缺失或重复、达到上限则如实停止。
        </p>
      )}
      {dryRunCancelled && (
        <p role="status" className="mt-1.5 text-xs text-[var(--lumi-text-secondary)]">
          已中止，本次试跑未完成。
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

/** Atom 预览折叠区 —— 前 ≤3 条 entry 的最终形态。 */
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

/** 用样例预览（离线零网络）：粘贴 JSON → 结构候选 → 试映射。 */
function SamplePreviewPanel({
  itemsExpr,
  fieldMap,
  onItemsExprChange,
  onFieldMapChange,
  onSampleParsed,
}: {
  itemsExpr: string
  fieldMap: ApiSourceFieldMapState
  onItemsExprChange: (next: string) => void
  onFieldMapChange: (next: ApiSourceFieldMapState) => void
  onSampleParsed: (sample: unknown | null) => void
}) {
  const [sampleText, setSampleText] = useState('')
  const [parseError, setParseError] = useState<string | null>(null)
  const samplePreviewMutation = useApiSourceSamplePreviewMutation()
  const abortRef = useRef<AbortController | null>(null)
  const [samplePreview, setSamplePreview] = useState<ApiSourcePreviewResult | null>(null)
  const [cancelled, setCancelled] = useState(false)

  useEffect(
    () => () => abortRef.current?.abort(),
    [],
  )

  const sample = useMemo(
    () => (sampleText.trim() === '' ? null : parseSampleJson(sampleText)),
    [sampleText],
  )

  // 解析结果上报给向导（第 3 步字段映射用样例键下拉）。
  useEffect(() => {
    onSampleParsed(sample)
  }, [sample, onSampleParsed])

  const options = useMemo(
    () => (sample === null ? { itemsExprs: [], fieldKeys: [] } : sampleFieldOptions(sample)),
    [sample],
  )

  const applySample = () => {
    if (sample === null) {
      setParseError('不是合法 JSON，请检查后重试。')
      return
    }
    setParseError(null)
    setCancelled(false)
    const controller = new AbortController()
    abortRef.current = controller
    samplePreviewMutation.mutate(
      {
        samplePayload: sample,
        itemsExpr: itemsExpr.trim(),
        fieldMap: Object.fromEntries(
          Object.entries(fieldMap).filter(([, value]) => value.trim() !== ''),
        ) as ApiSourceFieldMapState,
        signal: controller.signal,
      },
      {
        onSuccess: (result) => setSamplePreview(result),
        onError: (error) => {
          if (!isAbortError(error)) setSamplePreview(null)
        },
      },
    )
  }

  const fieldOptionNodes = options.fieldKeys.map((key) => (
    <option key={key} value={toFieldExpr(key)}>
      {key}
    </option>
  ))

  return (
    <fieldset
      className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3"
      data-sample-panel=""
    >
      <legend className="px-1 text-xs font-medium text-[var(--lumi-text-primary)]">
        用样例预览（离线：不访问 endpoint，不存储任何内容）
      </legend>
      <label htmlFor="api-source-sample-json" className="mt-1 block text-xs text-[var(--lumi-text-secondary)]">
        粘贴一段上游会返回的 JSON 样例
      </label>
      <textarea
        id="api-source-sample-json"
        value={sampleText}
        onChange={(e) => {
          setSampleText(e.target.value)
          setSamplePreview(null)
        }}
        rows={7}
        spellCheck={false}
        placeholder='例如：[{"id": 1, "name": "标题", "html_url": "https://…"}]'
        className="mt-1 w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-2 font-mono text-xs text-[var(--lumi-text-primary)]"
      />
      {parseError !== null && (
        <p role="alert" className="mt-1 text-xs text-[var(--lumi-danger)]">
          {parseError}
        </p>
      )}
      {parseError === null && sampleText.trim() !== '' && sample === null && (
        <p role="alert" className="mt-1 text-xs text-[var(--lumi-danger)]" data-sample-json-invalid="">
          不是合法 JSON，请检查后重试。
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]">
          items 取自
          <select
            aria-label="items 表达式（由样例结构生成）"
            value={itemsExpr}
            onChange={(e) => onItemsExprChange(e.target.value)}
            disabled={options.itemsExprs.length === 0}
            className="max-w-52 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs text-[var(--lumi-text-primary)]"
          >
            <option value="">（选择数组位置）</option>
            {options.itemsExprs.map((expr) => (
              <option key={expr} value={expr}>
                {expr}
              </option>
            ))}
          </select>
        </label>
        {samplePreviewMutation.isPending ? (
          <Button size="sm" variant="secondary" onClick={() => abortRef.current?.abort()}>
            中止预览
          </Button>
        ) : (
          <Button
            size="sm"
            variant="secondary"
            onClick={applySample}
            disabled={sample === null || itemsExpr.trim() === ''}
          >
            <RefreshCw aria-hidden className="size-3.5" />
            用样例预览
          </Button>
        )}
      </div>
      {cancelled && (
        <p role="status" className="mt-1 text-xs text-[var(--lumi-text-secondary)]">
          已中止，本次预览未完成。
        </p>
      )}
      {options.fieldKeys.length > 0 && (
        <div className="mt-2 grid grid-cols-1 gap-1.5 sm:grid-cols-2">
          {FIELD_MAP_FIELDS.map((field) => (
            <label key={field.key} className="flex items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]">
              <span className="w-16 shrink-0">{field.key}</span>
              <select
                aria-label={`${field.key} 字段（样例键）`}
                value={fieldMap[field.key]}
                onChange={(e) => {
                  onFieldMapChange({ ...fieldMap, [field.key]: e.target.value })
                }}
                className="min-w-0 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs text-[var(--lumi-text-primary)]"
              >
                <option value="">（不映射）</option>
                {fieldOptionNodes}
              </select>
            </label>
          ))}
        </div>
      )}
      <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]">
        下拉候选来自样例的真实结构（顶层键 + 首个数组元素键）；选择即生成 JMESPath 并回填表单。
        样例中缺失的 id/title 会被服务端如实拒绝，不会编造数据。
      </p>
      {samplePreviewMutation.isError && !isAbortError(samplePreviewMutation.error) && (
        <p role="alert" className="mt-1 text-xs leading-relaxed text-[var(--lumi-danger)]">
          <AlertCircle aria-hidden className="mr-1 inline size-3.5" />
          {samplePreviewMutation.error instanceof Error ? samplePreviewMutation.error.message : '样例预览失败。'}
        </p>
      )}
      {samplePreview !== null && samplePreview.sampleMode && (
        <div className="mt-2" data-sample-preview-ok="">
          <p className="flex items-center gap-1 text-[11px] text-[var(--lumi-accent-text)]">
            <CheckCircle2 aria-hidden className="size-3" />
            样例模式（离线）：以下与 FreshRSS 实际摄取的渲染管线一致。
          </p>
          <PreviewTable preview={samplePreview} />
          <AtomPreviewSection preview={samplePreview} />
        </div>
      )}
    </fieldset>
  )
}

/** 一次性成功面板：atomPath 只在创建响应里出现，刷新即丢失。 */
function CreatedPanel({ created, onClose }: { created: ApiSource; onClose: () => void }): ReactElement {
  return (
    <div role="status" className="flex flex-col gap-3" data-create-success="">
      <p className="flex items-center gap-1.5 text-sm font-medium text-[var(--lumi-text-primary)]">
        <CheckCircle2 aria-hidden className="size-4 text-[var(--lumi-category-green)]" />
        已创建「{created.name}」并尝试自动订阅
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
      <Button variant="primary" size="sm" onClick={onClose}>
        完成
      </Button>
    </div>
  )
}

export function CreateApiSourceWizard({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const [step, setStep] = useState(0)
  const [name, setName] = useState('')
  const [endpoint, setEndpoint] = useState('')
  const [itemsExpr, setItemsExpr] = useState('')
  const [fieldMap, setFieldMap] = useState<ApiSourceFieldMapState>(EMPTY_FIELD_MAP)
  const [pagination, setPagination] = useState<ApiSourcePaginationInput>({ mode: 'none' })
  const [sample, setSample] = useState<unknown | null>(null)
  const [preview, setPreview] = useState<ApiSourcePreviewResult | null>(null)
  const [previewCancelled, setPreviewCancelled] = useState(false)
  const [dryRun, setDryRun] = useState<ApiSourcePreviewResult | null>(null)
  const [dryRunCancelled, setDryRunCancelled] = useState(false)
  const [previewTab, setPreviewTab] = useState<'live' | 'sample'>('live')
  const [created, setCreated] = useState<ApiSource | null>(null)

  const createMutation = useCreateApiSourceMutation()
  const previewMutation = useApiSourcePreviewMutation()
  const dryRunMutation = useApiSourcePreviewMutation()
  const previewAbortRef = useRef<AbortController | null>(null)
  const dryRunAbortRef = useRef<AbortController | null>(null)

  // 关闭 / 卸载即中止在途预览与试抓。
  useEffect(() => {
    if (!open) {
      previewAbortRef.current?.abort()
      dryRunAbortRef.current?.abort()
    }
  }, [open])
  useEffect(
    () => () => {
      previewAbortRef.current?.abort()
      dryRunAbortRef.current?.abort()
    },
    [],
  )

  const endpointOk = useMemo(() => {
    try {
      const parsed = new URL(endpoint.trim())
      return parsed.protocol === 'http:' || parsed.protocol === 'https:'
    } catch {
      return false
    }
  }, [endpoint])

  const canNext =
    (step !== 0 || (name.trim() !== '' && endpointOk)) &&
    (step !== 1 || itemsExpr.trim() !== '')

  const reset = () => {
    setStep(0)
    setName('')
    setEndpoint('')
    setItemsExpr('')
    setFieldMap(EMPTY_FIELD_MAP)
    setPagination({ mode: 'none' })
    setSample(null)
    setPreview(null)
    setPreviewCancelled(false)
    setDryRun(null)
    setDryRunCancelled(false)
    setPreviewTab('live')
    setCreated(null)
    createMutation.reset()
    previewMutation.reset()
    dryRunMutation.reset()
  }

  const close = () => {
    onClose()
    // 关闭即重置：atomPath 一次性语义不允许「重开还能看到旧 secret」。
    reset()
  }

  const runPreview = () => {
    const controller = new AbortController()
    previewAbortRef.current = controller
    setPreviewCancelled(false)
    previewMutation.mutate(
      {
        endpoint: endpoint.trim(),
        itemsExpr: itemsExpr.trim(),
        fieldMap: { ...fieldMap },
        signal: controller.signal,
      },
      {
        onSuccess: (result) => setPreview(result),
        onError: (error) => {
          if (isAbortError(error)) setPreviewCancelled(true)
        },
      },
    )
  }

  const runDryRun = () => {
    const controller = new AbortController()
    dryRunAbortRef.current = controller
    setDryRunCancelled(false)
    dryRunMutation.mutate(
      {
        endpoint: endpoint.trim(),
        itemsExpr: itemsExpr.trim(),
        fieldMap: { ...fieldMap },
        pagination: { ...pagination },
        dryRunPagination: true,
        signal: controller.signal,
      },
      {
        onSuccess: (result) => setDryRun(result),
        onError: (error) => {
          if (isAbortError(error)) setDryRunCancelled(true)
        },
      },
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

  const goNext = () => {
    setStep((current) => Math.min(WIZARD_STEPS.length - 1, current + 1))
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      title="新增 API 来源"
      footer={
        created !== null ? undefined : (
          <div className="flex w-full items-center justify-between gap-2" data-wizard-footer="">
            <Button variant="ghost" size="sm" onClick={close}>
              取消
            </Button>
            <div className="flex items-center gap-2">
              {step > 0 && (
                <Button variant="secondary" size="sm" onClick={() => setStep((s) => s - 1)}>
                  上一步
                </Button>
              )}
              {step < WIZARD_STEPS.length - 1 ? (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={goNext}
                  disabled={!canNext}
                  data-wizard-next=""
                >
                  下一步
                </Button>
              ) : (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={save}
                  disabled={createMutation.isPending}
                  data-wizard-save=""
                >
                  {createMutation.isPending ? '保存中…' : '保存并订阅'}
                </Button>
              )}
            </div>
          </div>
        )
      }
    >
      {created !== null ? (
        <CreatedPanel created={created} onClose={close} />
      ) : (
        <div className="flex flex-col gap-4">
          <StepIndicator current={step} />

          {step === 0 && (
            <div className="flex flex-col gap-3" data-wizard-step="address">
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
              {endpoint.trim() !== '' && !endpointOk && (
                <p role="alert" className="text-xs text-[var(--lumi-danger)]">
                  地址需为 http(s) 完整 URL。
                </p>
              )}
              <p className="text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]">
                地址由服务端校验并代为访问；指向内网或本机地址的来源会被拒绝。
              </p>
              <p className="text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]">
                若接口需要认证，请使用地址内自带的令牌参数；凭据只保存在服务端，界面不回显。
              </p>
            </div>
          )}

          {step === 1 && (
            <div className="flex flex-col gap-3" data-wizard-step="preview">
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
              <Tabs
                aria-label="预览方式"
                value={previewTab}
                onValueChange={setPreviewTab}
                options={[
                  { value: 'live', label: '在线预览' },
                  { value: 'sample', label: '用样例预览' },
                ]}
                panels={{
                  live: (
                    <div className="flex flex-col gap-3">
                      <div className="flex items-center gap-2">
                        {previewMutation.isPending ? (
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => previewAbortRef.current?.abort()}
                            data-preview-cancel=""
                          >
                            中止预览
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={runPreview}
                            disabled={!endpointOk || itemsExpr.trim() === ''}
                          >
                            <RefreshCw aria-hidden className="size-3.5" />
                            预览
                          </Button>
                        )}
                      </div>
                      {previewCancelled && (
                        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
                          已中止，本次预览未完成。
                        </p>
                      )}
                      {previewMutation.isError && !isAbortError(previewMutation.error) && (
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
                    </div>
                  ),
                  sample: (
                    <SamplePreviewPanel
                      itemsExpr={itemsExpr}
                      fieldMap={fieldMap}
                      onItemsExprChange={setItemsExpr}
                      onFieldMapChange={setFieldMap}
                      onSampleParsed={setSample}
                    />
                  ),
                }}
              />
            </div>
          )}

          {step === 2 && (
            <fieldset className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3" data-wizard-step="mapping">
              <legend className="px-1 text-xs font-medium text-[var(--lumi-text-primary)]">
                字段映射（JMESPath）
              </legend>
              <div className="mt-1 flex flex-col gap-2">
                {FIELD_MAP_FIELDS.map((field) =>
                  sample !== null ? (
                    (() => {
                      const options = sampleFieldOptions(sample)
                      return (
                        <label key={field.key} className="flex items-center gap-2">
                          <span className="w-20 shrink-0 text-xs text-[var(--lumi-text-secondary)]">
                            {field.label}
                          </span>
                          <select
                            aria-label={`${field.key} 字段（样例键）`}
                            value={fieldMap[field.key]}
                            onChange={(e) =>
                              setFieldMap((prev) => ({ ...prev, [field.key]: e.target.value }))
                            }
                            className="min-w-0 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs text-[var(--lumi-text-primary)]"
                          >
                            <option value="">（不映射）</option>
                            {options.fieldKeys.map((key) => (
                              <option key={key} value={toFieldExpr(key)}>
                                {key}
                              </option>
                            ))}
                          </select>
                        </label>
                      )
                    })()
                  ) : (
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
                  ),
                )}
              </div>
              <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]">
                {sample !== null
                  ? '候选来自第 2 步样例的真实结构；缺失的 id/title 会被服务端如实拒绝。'
                  : '填写各字段的 JMESPath 表达式；留空 = 不映射。'}
              </p>
            </fieldset>
          )}

          {step === 3 && (
            <div data-wizard-step="probe">
              <PaginationConfigBlock
                value={pagination}
                onChange={setPagination}
                dryRun={dryRun}
                dryRunPending={dryRunMutation.isPending}
                dryRunError={
                  dryRunMutation.isError && !isAbortError(dryRunMutation.error)
                    ? dryRunMutation.error instanceof Error
                      ? dryRunMutation.error.message
                      : '试跑失败。'
                    : null
                }
                dryRunCancelled={dryRunCancelled}
                onDryRun={runDryRun}
                onDryRunCancel={() => dryRunAbortRef.current?.abort()}
                canDryRun={endpointOk && itemsExpr.trim() !== ''}
              />
            </div>
          )}

          {step === 4 && (
            <dl className="flex flex-col gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3 text-xs" data-wizard-step="save">
              <div className="flex gap-2">
                <dt className="w-20 shrink-0 text-[var(--lumi-text-tertiary)]">名称</dt>
                <dd className="min-w-0 flex-1 break-all text-[var(--lumi-text-primary)]">{name.trim()}</dd>
              </div>
              <div className="flex gap-2">
                <dt className="w-20 shrink-0 text-[var(--lumi-text-tertiary)]">地址</dt>
                <dd className="min-w-0 flex-1 break-all text-[var(--lumi-text-primary)]">{endpoint.trim()}</dd>
              </div>
              <div className="flex gap-2">
                <dt className="w-20 shrink-0 text-[var(--lumi-text-tertiary)]">列表表达式</dt>
                <dd className="min-w-0 flex-1 break-all font-mono text-[var(--lumi-text-primary)]">{itemsExpr.trim()}</dd>
              </div>
              <div className="flex gap-2">
                <dt className="w-20 shrink-0 text-[var(--lumi-text-tertiary)]">字段映射</dt>
                <dd className="min-w-0 flex-1 break-all font-mono text-[var(--lumi-text-secondary)]">
                  {FIELD_MAP_FIELDS.filter((f) => fieldMap[f.key].trim() !== '')
                    .map((f) => `${f.key}=${fieldMap[f.key]}`)
                    .join('，') || '（未映射）'}
                </dd>
              </div>
              <div className="flex gap-2">
                <dt className="w-20 shrink-0 text-[var(--lumi-text-tertiary)]">分页</dt>
                <dd className="min-w-0 flex-1 text-[var(--lumi-text-secondary)]">
                  {pagination.mode === 'none'
                    ? '不分页（单次抓取）'
                    : pagination.mode === 'page'
                      ? `页码 ?${pagination.page_param ?? 'page'}=N，最多 ${pagination.max_pages ?? 5} 页`
                      : `游标 ${pagination.cursor_path ?? ''}，最多 ${pagination.max_pages ?? 5} 页`}
                </dd>
              </div>
              <p className="text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]">
                保存后 Lumi 生成 Atom 地址并自动尝试订阅 FreshRSS；地址仅显示一次。
              </p>
              {createMutation.isError && (
                <p role="alert" className="flex items-start gap-1.5 leading-relaxed text-[var(--lumi-danger)]">
                  <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
                  {createMutation.error.message}
                </p>
              )}
            </dl>
          )}
        </div>
      )}
    </Dialog>
  )
}
