/** SourceBundleBlocks — N011：设置 → 订阅与来源 的组合包导出/导入。
 *
 * - 导出组合包：所选订阅 → 凭据无关 JSON 下载（Lumi 生成源脱敏为
 *   urn；只含 feed_url/title/category/type，绝无密钥）。
 * - 导入组合包：粘贴/选择 JSON → 默认试运行预览（new/exists/
 *   needs_credentials + category_action 逐项呈现）→ 确认后 apply；
 *   凭据型来源导入为停用草稿；重复导入幂等（全部 exists）。
 *
 * 所有 HTTP 经 src/api/client.ts；状态为本地 useMutation/useQuery。
 */

import { useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, Download, PackageOpen, Upload } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import type { BundleDocument, BundleImportResult } from '../../api/client'
import { exportSourceBundle, importSourceBundle } from '../../api/client'
import { useSubscriptions } from '../../api/queries'
import { Button } from '../ui/Button'
import { cx } from '../ui/cx'

const STATUS_LABELS: Record<BundleImportResult['items'][number]['status'], string> = {
  new: '新订阅',
  exists: '已存在',
  needs_credentials: '需凭据（导入为停用草稿）',
  invalid: '无效地址',
  failed: '订阅失败',
}

const CATEGORY_ACTION_LABELS: Record<string, string> = {
  none: '不分类',
  reuse: '复用现有分类',
  create: '将创建分类',
}

function errorText(error: unknown, fallback: string): string {
  if (error instanceof Error) return error.message
  return fallback
}

function downloadBundle(bundle: BundleDocument): void {
  const blob = new Blob([JSON.stringify(bundle, null, 2)], {
    type: 'application/json',
  })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'lumirss-sources-bundle.json'
  anchor.click()
  URL.revokeObjectURL(url)
}

/** 导出组合包（全库；服务端逐条脱敏）。 */
export function BundleExportBlock() {
  const subscriptions = useSubscriptions()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const exportAll = async () => {
    setBusy(true)
    setError(null)
    setDone(false)
    try {
      const feedUrls =
        subscriptions.data !== undefined
          ? subscriptions.data.map((s) => s.feedUrl)
          : []
      const bundle = await exportSourceBundle(feedUrls)
      downloadBundle(bundle)
      setDone(true)
    } catch (err) {
      setError(errorText(err, '导出失败，请稍后重试。'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5" data-bundle-export="">
      <p className="text-sm font-medium text-[var(--lumi-text-primary)]">导出组合包</p>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        把订阅列表打包成凭据无关的 JSON 文件（只含地址/标题/分类/类型）。
        Lumi 生成的来源（API、邮件桥）会脱敏为占位标识，不会携带任何密钥。
      </p>
      <div className="mt-3 flex items-center gap-2">
        <Button
          size="sm"
          onClick={() => void exportAll()}
          disabled={busy || subscriptions.isPending}
          data-bundle-export-go=""
        >
          <Download aria-hidden className="size-3.5" />
          {busy ? '导出中…' : '导出组合包'}
        </Button>
        {done && (
          <span role="status" className="flex items-center gap-1 text-xs text-[var(--lumi-text-secondary)]">
            <CheckCircle2 aria-hidden className="size-3.5 text-[var(--lumi-accent-text)]" />
            已开始下载
          </span>
        )}
      </div>
      {error !== null && (
        <p role="alert" className="mt-2 flex items-center gap-1.5 text-xs text-[var(--lumi-danger)]">
          <AlertCircle aria-hidden className="size-3.5 shrink-0" />
          {error}
        </p>
      )}
    </div>
  )
}

/** 导入组合包：预览 → 确认应用。 */
export function BundleImportBlock() {
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [bundle, setBundle] = useState<BundleDocument | null>(null)
  const [preview, setPreview] = useState<BundleImportResult | null>(null)
  const [result, setResult] = useState<BundleImportResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reset = () => {
    setBundle(null)
    setPreview(null)
    setResult(null)
    setError(null)
    if (fileInputRef.current !== null) fileInputRef.current.value = ''
  }

  const loadBundle = async (file: File) => {
    reset()
    setBusy(true)
    try {
      const parsed = JSON.parse(await file.text()) as BundleDocument
      if (!Array.isArray(parsed.sources)) throw new Error('缺少 sources 数组')
      setBundle(parsed)
      setPreview(await importSourceBundle(parsed, false))
    } catch (err) {
      setError(errorText(err, '不是合法的组合包文件。'))
    } finally {
      setBusy(false)
    }
  }

  const apply = async () => {
    if (bundle === null) return
    setBusy(true)
    setError(null)
    try {
      const applied = await importSourceBundle(bundle, true)
      setResult(applied)
      setPreview(null)
      await queryClient.invalidateQueries({ queryKey: ['subscriptions'] })
    } catch (err) {
      setError(errorText(err, '导入失败，请稍后重试。'))
    } finally {
      setBusy(false)
    }
  }

  const items = result !== null ? result.items : (preview?.items ?? [])

  return (
    <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5" data-bundle-import="">
      <p className="text-sm font-medium text-[var(--lumi-text-primary)]">导入组合包</p>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        选择组合包 JSON 后先预览（逐项：新订阅 / 已存在 / 需凭据），确认后才写入。
        需要凭据的类型不会复制密钥，只会导入为停用草稿；重复导入幂等（全部「已存在」）。
      </p>
      <div className="mt-3 flex items-center gap-2">
        <label htmlFor="bundle-import-file" className="cursor-pointer">
          <span className="flex min-h-11 items-center gap-2 text-sm text-[var(--lumi-text-primary)]">
            <Upload aria-hidden className="size-4" />
            选择组合包文件
          </span>
          <input
            ref={fileInputRef}
            id="bundle-import-file"
            type="file"
            accept=".json,application/json"
            disabled={busy}
            className="sr-only"
            data-bundle-import-file=""
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) void loadBundle(file)
            }}
          />
        </label>
      </div>
      {busy && (
        <p role="status" className="mt-2 text-xs text-[var(--lumi-text-secondary)]">
          处理中…
        </p>
      )}
      {error !== null && (
        <p role="alert" className="mt-2 flex items-center gap-1.5 text-xs text-[var(--lumi-danger)]">
          <AlertCircle aria-hidden className="size-3.5 shrink-0" />
          {error}
        </p>
      )}
      {items.length > 0 && (
        <div className="mt-3 flex flex-col gap-1" data-bundle-items="">
          {items.map((item) => (
            <p key={item.feedUrl} className="flex flex-wrap items-center gap-x-2 text-xs text-[var(--lumi-text-secondary)]">
              <span
                className={cx(
                  'shrink-0 rounded-[var(--lumi-radius-full)] px-1.5 py-0.5 text-[10px]',
                  item.status === 'new' && 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]',
                  item.status === 'exists' && 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-tertiary)]',
                  (item.status === 'needs_credentials' || item.status === 'invalid' || item.status === 'failed') &&
                    'bg-[var(--lumi-danger)]/10 text-[var(--lumi-danger)]',
                )}
              >
                {STATUS_LABELS[item.status]}
              </span>
              <span className="min-w-0 truncate" title={item.feedUrl}>
                {item.title !== '' ? item.title : item.feedUrl}
              </span>
              {item.categoryAction !== 'none' && (
                <span className="text-[10px] text-[var(--lumi-text-tertiary)]">
                  {CATEGORY_ACTION_LABELS[item.categoryAction]}
                </span>
              )}
            </p>
          ))}
        </div>
      )}
      {result !== null && (
        <p role="status" className="mt-2 flex items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]" data-bundle-done="">
          <PackageOpen aria-hidden className="size-3.5 text-[var(--lumi-accent-text)]" />
          导入完成：新订阅 {result.counts.new ?? 0} · 已存在 {result.counts.exists ?? 0} · 草稿{' '}
          {result.counts.needs_credentials ?? 0}
        </p>
      )}
      {preview !== null && (
        <div className="mt-3 flex gap-2">
          <Button size="sm" variant="primary" onClick={() => void apply()} disabled={busy} data-bundle-apply="">
            确认导入
          </Button>
          <Button size="sm" variant="ghost" onClick={reset} disabled={busy}>
            重新选择
          </Button>
        </div>
      )}
    </div>
  )
}
