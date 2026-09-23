/** ObsidianDevicesSection — P16「设备与导出」：设备档案 CRUD + 导出模板
 * 编辑器（实时预览）+ 两种 Vault 模式的诚实说明。
 *
 * - 设备档案描述「用户自己设备上的 Obsidian vault 名称」，只用于生成
 *   obsidian:// 链接；与服务器端 vault_path（env 只读挂载 / 手动路径）
 *   完全无关 —— 文案必须把两者讲清楚，不混淆。
 * - 模板编辑：允许变量 chips + 防抖预览（POST preview，夹具文本）；
 *   unknownVars 由服务端返回，UI 以 role=alert 诚实列出（不静默）。
 * - 模板空串 = 跟随默认模板（默认内容以 placeholder 展示）。 */

import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, Loader2, Pencil, Plus, RotateCcw, Save, Trash2 } from 'lucide-react'
import type { ObsidianDeviceProfile } from '../../api/client'
import {
  useCreateObsidianDeviceMutation,
  useDeleteObsidianDeviceMutation,
  useObsidianDevices,
  useObsidianExportTemplate,
  useObsidianTemplatePreviewMutation,
  useUpdateObsidianDeviceMutation,
  useUpdateObsidianExportTemplateMutation,
} from '../../api/queries'
import { Button } from '../ui/Button'
import { Select } from '../ui/Select'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'

const PLATFORM_OPTIONS = [
  { value: 'windows', label: 'Windows' },
  { value: 'ios', label: 'iPhone / iOS' },
  { value: 'ipados', label: 'iPad / iPadOS' },
  { value: 'other', label: '其他平台' },
] as const

const inputCls = cx(
  'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 min-h-9 text-sm',
  'text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)]',
  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
  'disabled:cursor-not-allowed disabled:opacity-50',
)

function useDebounced(value: string, delayMs = 400): string {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])
  return debounced
}

interface DeviceFormValue {
  label: string
  vaultName: string
  vaultIdentifier: string
  platform: string
}

const EMPTY_FORM: DeviceFormValue = { label: '', vaultName: '', vaultIdentifier: '', platform: 'windows' }

function DeviceForm({
  initial,
  submitLabel,
  pending,
  error,
  onSubmit,
  onCancel,
}: {
  initial: DeviceFormValue
  submitLabel: string
  pending: boolean
  error: string | null
  onSubmit: (value: DeviceFormValue) => void
  onCancel?: () => void
}) {
  const [value, setValue] = useState<DeviceFormValue>(initial)
  const canSubmit = value.label.trim() !== '' && value.vaultName.trim() !== '' && !pending

  return (
    <form
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (canSubmit) onSubmit(value)
      }}
    >
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
          设备名称
          <input
            value={value.label}
            onChange={(e) => setValue({ ...value, label: e.target.value })}
            placeholder="例如：Windows 台式机"
            aria-label="设备名称"
            className={inputCls}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
          Vault 名称
          <input
            value={value.vaultName}
            onChange={(e) => setValue({ ...value, vaultName: e.target.value })}
            placeholder="Obsidian 里的库名，例如 MyVault"
            aria-label="Vault 名称"
            className={inputCls}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
          平台
          <Select
            aria-label="平台"
            value={value.platform}
            onChange={(e) => setValue({ ...value, platform: e.target.value })}
            options={PLATFORM_OPTIONS.map((o) => ({ ...o }))}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
          本地标识（可选）
          <input
            value={value.vaultIdentifier}
            onChange={(e) => setValue({ ...value, vaultIdentifier: e.target.value })}
            placeholder="Obsidian 的本地 vault id（选填）"
            aria-label="本地标识（可选）"
            className={inputCls}
          />
        </label>
      </div>
      {error !== null && (
        <p role="alert" className="flex items-start gap-1.5 text-xs text-[var(--lumi-danger)]">
          <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          {error}
        </p>
      )}
      <div className="flex items-center gap-2">
        <Button type="submit" size="sm" variant="primary" disabled={!canSubmit}>
          {pending ? <Loader2 aria-hidden className="size-3.5 animate-spin" /> : <Plus aria-hidden className="size-3.5" />}
          {submitLabel}
        </Button>
        {onCancel !== undefined && (
          <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
            取消
          </Button>
        )}
      </div>
    </form>
  )
}

function DeviceRow({
  device,
  onDelete,
  deletePending,
}: {
  device: ObsidianDeviceProfile
  onDelete: () => void
  deletePending: boolean
}) {
  const update = useUpdateObsidianDeviceMutation()
  const [editing, setEditing] = useState(false)
  const platformLabel =
    PLATFORM_OPTIONS.find((o) => o.value === device.platform)?.label ?? device.platform

  if (editing) {
    return (
      <li>
        <DeviceForm
          initial={{
            label: device.label,
            vaultName: device.vaultName,
            vaultIdentifier: device.vaultIdentifier,
            platform: device.platform,
          }}
          submitLabel="保存修改"
          pending={update.isPending}
          error={update.isError ? update.error.message : null}
          onSubmit={(value) =>
            update.mutate(
              {
                deviceId: device.id,
                payload: {
                  label: value.label.trim(),
                  vaultName: value.vaultName.trim(),
                  vaultIdentifier: value.vaultIdentifier.trim(),
                  platform: value.platform as ObsidianDeviceProfile['platform'],
                },
              },
              { onSuccess: () => setEditing(false) },
            )
          }
          onCancel={() => setEditing(false)}
        />
      </li>
    )
  }

  return (
    <li
      className={cx(
        'flex min-h-11 items-center gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-3 py-2',
      )}
      data-lumi-obsidian-device={device.label}
    >
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-[var(--lumi-text-primary)]">
          {device.label}
        </span>
        <span className="block truncate text-xs text-[var(--lumi-text-tertiary)]">
          {platformLabel} · Vault：{device.vaultName}
          {device.vaultIdentifier !== '' ? ` · ${device.vaultIdentifier}` : ''}
        </span>
      </span>
      <Button
        size="sm"
        variant="ghost"
        aria-label={`编辑设备 ${device.label}`}
        onClick={() => setEditing(true)}
      >
        <Pencil aria-hidden className="size-3.5" />
        编辑
      </Button>
      <Button
        size="sm"
        variant="ghost"
        aria-label={`删除设备 ${device.label}`}
        disabled={deletePending}
        onClick={onDelete}
      >
        <Trash2 aria-hidden className="size-3.5" />
        删除
      </Button>
    </li>
  )
}

function TemplateEditor() {
  const template = useObsidianExportTemplate()
  const save = useUpdateObsidianExportTemplateMutation()
  const preview = useObsidianTemplatePreviewMutation()
  const [draft, setDraft] = useState<string | null>(null)
  const [savedFlash, setSavedFlash] = useState(false)

  const current = draft ?? template.data?.template ?? ''
  const debounced = useDebounced(current)

  // 实时预览：草稿防抖后交给服务端渲染（夹具文本；未知变量诚实返回）。
  useEffect(() => {
    if (template.data === undefined) return
    preview.mutate({ template: debounced })
    // preview.mutate 引用稳定（useMutation）；debounced 变化即重放。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced, template.data])

  const unknownVars = preview.data?.unknownVars ?? []
  const followingDefault = template.data !== undefined && template.data.template === ''

  const saveDraft = () => {
    save.mutate(current, {
      onSuccess: () => {
        setDraft(null)
        setSavedFlash(true)
        window.setTimeout(() => setSavedFlash(false), 2000)
      },
    })
  }

  const resetToDefault = () => {
    save.mutate('', {
      onSuccess: () => setDraft(null),
    })
  }

  return (
    <div className="flex flex-col gap-2" data-lumi-obsidian-template-editor="">
      {template.isPending ? (
        <div aria-label="导出模板加载中">
          <Skeleton className="h-24 w-full" />
        </div>
      ) : template.isError ? (
        <p role="alert" className="text-sm text-[var(--lumi-danger)]">
          导出模板加载失败：{template.error.message}
        </p>
      ) : (
        <>
          <label className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
            导出模板
            <textarea
              value={current}
              onChange={(e) => setDraft(e.target.value)}
              rows={5}
              aria-label="导出模板"
              placeholder={template.data?.defaultTemplate}
              className={cx(inputCls, 'font-mono leading-relaxed')}
            />
          </label>
          {followingDefault && draft === null && (
            <p className="text-xs text-[var(--lumi-text-tertiary)]" role="status">
              当前使用默认模板（输入可覆盖；占位文本即默认内容）。
            </p>
          )}
          <div className="flex flex-wrap items-center gap-1.5" aria-label="允许的模板变量">
            {(template.data?.allowedVars ?? []).map((v) => (
              <code
                key={v}
                className="rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-1.5 py-0.5 text-[11px] text-[var(--lumi-text-secondary)]"
              >
                {`{{${v}}}`}
              </code>
            ))}
          </div>

          {unknownVars.length > 0 && (
            <p role="alert" className="text-xs leading-relaxed text-[var(--lumi-danger)]">
              模板含不支持的变量：{unknownVars.map((v) => `{{${v}}}`).join('、')}
              （导出时将按空值渲染并在交接提示中注明）。
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="primary" disabled={save.isPending || draft === null} onClick={saveDraft}>
              <Save aria-hidden className="size-3.5" />
              {save.isPending ? '保存中…' : '保存模板'}
            </Button>
            <Button size="sm" variant="ghost" disabled={save.isPending || followingDefault} onClick={resetToDefault}>
              <RotateCcw aria-hidden className="size-3.5" />
              恢复默认
            </Button>
            {savedFlash && (
              <span role="status" className="text-xs text-[var(--lumi-accent-text)]">
                模板已保存
              </span>
            )}
            {save.isError && (
              <span role="alert" className="text-xs text-[var(--lumi-danger)]">
                {save.error.message}
              </span>
            )}
          </div>

          <div className="flex flex-col gap-1" data-lumi-obsidian-preview="">
            <span className="text-xs font-medium text-[var(--lumi-text-secondary)]">
              实时预览（示例文章）
            </span>
            {preview.isPending ? (
              <Skeleton className="h-20 w-full" />
            ) : preview.isError ? (
              <p role="alert" className="text-xs text-[var(--lumi-danger)]">
                预览失败：{preview.error.message}
              </p>
            ) : (
              <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3 text-xs leading-relaxed text-[var(--lumi-text-primary)]">
                {preview.data?.text}
              </pre>
            )}
          </div>
        </>
      )}
    </div>
  )
}

export default function ObsidianDevicesSection({ envRootConfigured }: { envRootConfigured: boolean }) {
  const devices = useObsidianDevices()
  const create = useCreateObsidianDeviceMutation()
  const remove = useDeleteObsidianDeviceMutation()
  const [open, setOpen] = useState(false)
  const [adding, setAdding] = useState(false)

  const items = useMemo(() => devices.data?.items ?? [], [devices.data])

  return (
    <section
      aria-label="设备与导出"
      className="border-t border-[var(--lumi-separator)] px-3 py-4 max-lg:pb-[84px]"
      data-lumi-obsidian-devices-section=""
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 rounded-[var(--lumi-radius-md)] px-1 py-1.5 text-left focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
      >
        <h2 className="text-sm font-semibold text-[var(--lumi-text-primary)]">设备与导出</h2>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">
          {open ? '收起' : `展开（${items.length} 台设备）`}
        </span>
      </button>

      <p className="mt-1.5 px-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        {envRootConfigured
          ? '当前为环境挂载模式：宿主 Vault 以只读方式挂载进服务器（用于索引与阅读）。'
          : '当前为手动路径模式：服务器上配置的 Vault 路径只用于只读索引。'}
        设备档案与此无关——它描述你自己设备（电脑 / 手机）上的 Obsidian 库名，
        仅用于生成 obsidian:// 打开链接。Lumi 永远只读 Vault，不会替你写入。
      </p>

      {open && (
        <div className="mt-3 flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <h3 className="text-xs font-medium text-[var(--lumi-text-secondary)]">设备档案</h3>
              {!adding && (
                <Button size="sm" variant="secondary" aria-label="新增设备档案" onClick={() => setAdding(true)}>
                  <Plus aria-hidden className="size-3.5" />
                  添加设备
                </Button>
              )}
            </div>
            {devices.isPending ? (
              <ul className="flex flex-col gap-2" aria-label="设备列表加载中">
                {[0, 1].map((i) => (
                  <li key={i}>
                    <Skeleton className="h-11 w-full" />
                  </li>
                ))}
              </ul>
            ) : devices.isError ? (
              <div className="flex flex-col gap-2">
                <p role="alert" className="text-xs text-[var(--lumi-danger)]">
                  设备列表加载失败：{devices.error.message}
                </p>
                <Button size="sm" variant="secondary" onClick={() => devices.refetch()}>
                  重试
                </Button>
              </div>
            ) : (
              <ul className="flex flex-col gap-2" aria-label="设备档案列表">
                {items.map((device) => (
                  <DeviceRow
                    key={device.id}
                    device={device}
                    deletePending={remove.isPending && remove.variables === device.id}
                    onDelete={() => remove.mutate(device.id)}
                  />
                ))}
                {items.length === 0 && !adding && (
                  <li className="rounded-[var(--lumi-radius-lg)] border border-dashed border-[var(--lumi-border)] px-3 py-3 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
                    还没有设备档案。添加一台（例如 Windows、iPhone），阅读页的
                    「导出到 Obsidian」就能把文章交给它打开。
                  </li>
                )}
              </ul>
            )}
            {adding && (
              <DeviceForm
                initial={EMPTY_FORM}
                submitLabel="添加设备"
                pending={create.isPending}
                error={create.isError ? create.error.message : null}
                onSubmit={(value) =>
                  create.mutate(
                    {
                      label: value.label.trim(),
                      vaultName: value.vaultName.trim(),
                      vaultIdentifier: value.vaultIdentifier.trim(),
                      platform: value.platform as ObsidianDeviceProfile['platform'],
                    },
                    {
                      onSuccess: () => {
                        setAdding(false)
                        if (!open) setOpen(true)
                      },
                    },
                  )
                }
                onCancel={() => setAdding(false)}
              />
            )}
          </div>

          <div className="flex flex-col gap-2">
            <h3 className="text-xs font-medium text-[var(--lumi-text-secondary)]">导出模板</h3>
            <TemplateEditor />
          </div>
        </div>
      )}
    </section>
  )
}
