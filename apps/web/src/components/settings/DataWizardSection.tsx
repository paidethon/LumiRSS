/** DataWizardSection — N010 个人数据迁出/迁入向导（数据控制页）。
 *
 * - 迁出：先看范围（scope：各组件条数；RSS 绑定不可用时 sources/
 *   readingState 如实「不可用」）→ 下载 zip（绝无秘密）；
 * - 迁入：上传 zip → 预览（各组件计数 + 冲突=已存在将跳过）→ 选择
 *   组件应用（跳过已存在、只加新的；readingState 只对已存在引用生效）。
 * 与完整运维备份用途分开；本向导不含服务密钥。 */

import { useRef, useState } from 'react'
import { Download, FileUp } from 'lucide-react'
import {
  ApiError,
  applyLumiDataImport,
  exportLumiDataZip,
  getLumiDataScope,
  previewLumiDataImport,
  type ImportApplyComponentResult,
  type ImportPreviewComponent,
} from '../../api/client'
import { useQuery } from '@tanstack/react-query'
import { Button } from '../ui/Button'

type WizardTab = 'export' | 'import'

export function DataWizardSection() {
  const [tab, setTab] = useState<WizardTab>('export')
  const scope = useQuery({ queryKey: ['lumi-data-scope'], queryFn: ({ signal }) => getLumiDataScope(signal) })
  const [exportError, setExportError] = useState<string | null>(null)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const [preview, setPreview] = useState<{ importId: string; components: ImportPreviewComponent[] } | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [applyResult, setApplyResult] = useState<Record<string, ImportApplyComponentResult> | null>(null)
  const [importError, setImportError] = useState<string | null>(null)
  const [importBusy, setImportBusy] = useState(false)

  async function handleExport() {
    setExportError(null)
    try {
      await exportLumiDataZip()
    } catch (error) {
      setExportError(error instanceof ApiError ? error.message : '导出失败，请稍后重试。')
    }
  }

  async function handlePreviewUpload(file: File) {
    setImportError(null)
    setPreview(null)
    setApplyResult(null)
    setSelected([])
    setImportBusy(true)
    try {
      const result = await previewLumiDataImport(file)
      setPreview(result)
    } catch (error) {
      setImportError(error instanceof ApiError ? error.message : '导入预览失败：不是有效的导出包。')
    } finally {
      setImportBusy(false)
    }
  }

  async function handleApply() {
    if (!preview || selected.length === 0) return
    setImportError(null)
    setImportBusy(true)
    try {
      const result = await applyLumiDataImport(preview.importId, selected)
      setApplyResult(result.components)
      setPreview(null)
    } catch (error) {
      setImportError(error instanceof ApiError ? error.message : '导入失败，请重新预览后再试。')
    } finally {
      setImportBusy(false)
    }
  }

  return (
    <section className="py-2" data-testid="lumi-data-wizard">
      <div
        className="flex gap-1 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] p-0.5"
        role="tablist"
        aria-label="个人数据向导"
      >
        {(['export', 'import'] as const).map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={
              tab === key
                ? 'min-h-9 flex-1 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-3 text-sm text-[var(--lumi-text-primary)]'
                : 'min-h-9 flex-1 rounded-[var(--lumi-radius-full)] px-3 text-sm text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]'
            }
          >
            {key === 'export' ? '迁出' : '迁入'}
          </button>
        ))}
      </div>

      {tab === 'export' && (
        <div className="mt-3 flex flex-col gap-2">
          {scope.isPending && <p className="text-xs text-[var(--lumi-text-tertiary)]">正在统计范围…</p>}
          {scope.isError && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">范围统计失败（服务端不可达）。</p>
          )}
          {scope.data && (
            <ul className="flex flex-col gap-1" data-testid="lumi-export-scope">
              {scope.data.components.map((component) => (
                <li
                  key={component.key}
                  className="flex min-h-9 items-center justify-between gap-2 text-xs"
                  data-scope-key={component.key}
                >
                  <span className="text-[var(--lumi-text-secondary)]">{component.label}</span>
                  {component.available ? (
                    <span className="shrink-0 text-[var(--lumi-text-primary)]">
                      {component.count} 项
                      {component.truncated ? '（超出上限，已诚实截断）' : ''}
                    </span>
                  ) : (
                    <span className="shrink-0 text-[var(--lumi-text-tertiary)]">不可用：{component.reason}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
          <div>
            <Button variant="primary" size="sm" onClick={handleExport} data-testid="lumi-export-zip">
              <Download aria-hidden className="size-4" />
              下载导出包（zip）
            </Button>
          </div>
          {exportError && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">{exportError}</p>
          )}
        </div>
      )}

      {tab === 'import' && (
        <div className="mt-3 flex flex-col gap-2">
          <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
            上传本实例导出的 zip：先预览各组件数量与冲突（已存在的将被跳过），
            再选择要合并的组件。已读/收藏状态只对当前账号已存在的条目生效。
          </p>
          <input
            ref={fileInputRef}
            type="file"
            accept=".zip,application/zip"
            className="hidden"
            aria-label="选择导出包文件"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) void handlePreviewUpload(file)
              event.target.value = ''
            }}
          />
          <div>
            <Button
              variant="secondary"
              size="sm"
              disabled={importBusy}
              onClick={() => fileInputRef.current?.click()}
              data-testid="lumi-import-choose"
            >
              <FileUp aria-hidden className="size-4" />
              {importBusy ? '处理中…' : '选择 zip 并预览'}
            </Button>
          </div>
          {importError && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]" data-testid="lumi-import-error">
              {importError}
            </p>
          )}
          {preview && (
            <div className="flex flex-col gap-2" data-testid="lumi-import-preview">
              <ul className="flex flex-col gap-1">
                {preview.components.map((component) => (
                  <li key={component.key} className="flex min-h-9 items-center justify-between gap-2 text-xs">
                    <label className="flex min-w-0 items-center gap-2">
                      <input
                        type="checkbox"
                        checked={selected.includes(component.key)}
                        onChange={(event) =>
                          setSelected((prev) =>
                            event.target.checked
                              ? [...prev, component.key]
                              : prev.filter((key) => key !== component.key),
                          )
                        }
                        aria-label={`导入 ${component.label}`}
                      />
                      <span className="truncate text-[var(--lumi-text-secondary)]">{component.label}</span>
                    </label>
                    <span className="shrink-0 text-[var(--lumi-text-primary)]">
                      {component.count} 项
                      {component.conflicts > 0 ? (
                        <span className="ml-1 text-[var(--lumi-warning, #d97706)]">（{component.conflicts} 已存在，将跳过）</span>
                      ) : null}
                    </span>
                  </li>
                ))}
              </ul>
              <div>
                <Button
                  variant="primary"
                  size="sm"
                  disabled={selected.length === 0 || importBusy}
                  onClick={handleApply}
                  data-testid="lumi-import-apply"
                >
                  {importBusy ? '合并中…' : `合并所选（${selected.length}）`}
                </Button>
              </div>
            </div>
          )}
          {applyResult && (
            <ul className="flex flex-col gap-1 text-xs" data-testid="lumi-import-result">
              {Object.entries(applyResult).map(([key, result]) => (
                <li key={key}>
                  {key}：
                  {'added' in result ? `新增 ${result.added ?? 0}` : `应用 ${result.applied ?? 0}`}
                  ，跳过 {result.skipped ?? 0}
                  {result.failed ? `，失败 ${result.failed}` : ''}
                  {result.reason ? `（${result.reason}）` : ''}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}
