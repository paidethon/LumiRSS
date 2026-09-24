/** ObsidianExportDialog — P16「导出到 Obsidian」交接对话框。
 *
 * 流程：选一个设备档案（GET /obsidian/devices）→【N139 先校验】
 * POST export-handoff/validate（只读报告：断链 wikilink / 缺失附件 /
 * 重复块 id）→ 无问题直接交接；有问题则诚实列出，用户可修正后重试或
 * 明确选择「仍然继续导出」→ POST export-handoff（服务端按模板渲染并
 * 裁决 uri / file）→ runObsidianHandoff 执行：
 * - mode='uri'：跳官方 obsidian://new 链接，文案「已打开 Obsidian（请在
 *   Obsidian 确认保存）」—— 诚实交接：Lumi 不写 Vault（ADR 0004），
 *   保存由用户在 Obsidian 确认；绝不显示「已写入」。
 * - mode='file'（tooLong）：下载 .md + 剪贴板，文案如实说明走了哪条路。
 * N135：UI 明确说明 obsidian:// URI 无法检测 Vault 内是否已有同名笔记
 * （官方 URI 限制）；重名靠导出设置的命名策略（默认时间戳后缀）缓解，
 * 文件下载路径自带唯一后缀、从不覆盖。
 * N137：「仅导出上次以来」= 只携带上次导出水位之后新增/修改的批注，
 * 附服务端增量预览（新增/修改计数）。
 * 复制失败 → 只读文本框诚实降级。无设备档案 → 空态引导去设置。 */

import { useState } from 'react'
import { AlertCircle, BookMarked, Clipboard, ListChecks } from 'lucide-react'
import type { EntryDetail } from '../api/types'
import type { ObsidianExportIssue } from '../api/client'
import {
  useAnnotationsExportDelta,
  useObsidianDevices,
  useObsidianExportHandoffMutation,
  useObsidianExportTemplate,
  useObsidianExportValidateMutation,
} from '../api/queries'
import { runObsidianHandoff, type HandoffOutcome } from '../lib/obsidian-handoff'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { EmptyState } from './ui/EmptyState'
import { Skeleton } from './ui/Skeleton'
import { cx } from './ui/cx'

const PLATFORM_LABELS: Record<string, string> = {
  windows: 'Windows',
  ios: 'iPhone / iOS',
  ipados: 'iPad / iPadOS',
  other: '其他平台',
}

const ISSUE_KIND_LABELS: Record<ObsidianExportIssue['kind'], string> = {
  broken_wikilink: '断链 wikilink',
  missing_attachment: '缺失附件',
  duplicate_block_id: '重复块 id',
}

export default function ObsidianExportDialog({
  open,
  detail,
  onClose,
}: {
  open: boolean
  detail: EntryDetail
  onClose: () => void
}) {
  const devices = useObsidianDevices()
  const templateView = useObsidianExportTemplate()
  const validate = useObsidianExportValidateMutation()
  const handoff = useObsidianExportHandoffMutation()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [onlySinceLastExport, setOnlySinceLastExport] = useState(false)
  const [outcome, setOutcome] = useState<HandoffOutcome | null>(null)
  const [issues, setIssues] = useState<ObsidianExportIssue[] | null>(null)
  const delta = useAnnotationsExportDelta(open ? detail.entryRef : null)

  const items = devices.data?.items ?? []
  const effectiveId =
    selectedId !== null && items.some((d) => d.id === selectedId)
      ? selectedId
      : (items[0]?.id ?? null)
  const policy = templateView.data?.exportNamePolicy ?? 'timestamp_suffix'

  const runHandoff = () => {
    if (effectiveId === null || handoff.isPending) return
    setOutcome(null)
    handoff.mutate(
      { entryRef: detail.entryRef, deviceId: effectiveId, onlySinceLastExport },
      {
        onSuccess: async (result) => {
          // 生成的 API 类型里 uri/reason 是可选的（`?: string | null`），
          // HandoffResultLike 契约要求显式 null —— 调用点归一化，缺省
          // 与 null 在 handoff 语义里等价（都走 file 回退分支）。
          setOutcome(
            await runObsidianHandoff({
              ...result,
              uri: result.uri ?? null,
              reason: result.reason ?? null,
            }),
          )
        },
      },
    )
  }

  const startExport = () => {
    if (effectiveId === null || validate.isPending) return
    setOutcome(null)
    setIssues(null)
    validate.mutate(
      { entryRef: detail.entryRef, deviceId: effectiveId, onlySinceLastExport },
      {
        onSuccess: (result) => {
          if (result.issues.length > 0) {
            // 只读校验报告：先展示，用户修正后重试或显式继续。
            setIssues(result.issues)
            return
          }
          runHandoff()
        },
        onError: () => {
          // 校验本身失败不阻塞交接（诚实降级：直接走既有交接路径）。
          runHandoff()
        },
      },
    )
  }

  const pending = validate.isPending || handoff.isPending

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="导出到 Obsidian"
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={onClose}>
            关闭
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={effectiveId === null || pending}
            onClick={issues !== null ? runHandoff : startExport}
          >
            <BookMarked aria-hidden className="size-3.5" />
            {validate.isPending
              ? '校验中…'
              : handoff.isPending
                ? '准备中…'
                : issues !== null
                  ? '仍然继续导出'
                  : '打开 Obsidian'}
          </Button>
        </>
      }
    >
      {devices.isPending ? (
        <div className="flex flex-col gap-2" aria-label="设备列表加载中">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-4/5" />
        </div>
      ) : devices.isError ? (
        <div className="flex flex-col gap-2">
          <p role="alert" className="text-sm text-[var(--lumi-danger)]">
            设备列表加载失败：{devices.error.message}
          </p>
          <Button size="sm" variant="secondary" onClick={() => devices.refetch()}>
            重试
          </Button>
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<BookMarked aria-hidden className="size-8" />}
          title="还没有设备档案"
          description="先在「Obsidian 库 → 设备与导出」里添加一台设备（例如 Windows、iPhone），再回来导出。设备档案只用于生成 obsidian:// 链接，Lumi 不会写入你的 Vault。"
        />
      ) : (
        <div className="flex flex-col gap-3">
          <div role="radiogroup" aria-label="选择目标设备" className="flex flex-col gap-1.5">
            {items.map((device) => (
              <label
                key={device.id}
                className={cx(
                  'flex min-h-11 cursor-pointer items-center gap-2.5 rounded-[var(--lumi-radius-lg)] border px-3 py-2 text-sm',
                  'transition-colors duration-[var(--lumi-motion-fast)]',
                  effectiveId === device.id
                    ? 'border-[var(--lumi-accent-text)] bg-[var(--lumi-surface-selected)]'
                    : 'border-[var(--lumi-border)] hover:bg-[var(--lumi-surface-hover)]',
                )}
              >
                <input
                  type="radio"
                  name="obsidian-export-device"
                  value={device.id}
                  checked={effectiveId === device.id}
                  onChange={() => {
                    setSelectedId(device.id)
                    setIssues(null)
                  }}
                  className="accent-[var(--lumi-accent-text)]"
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium text-[var(--lumi-text-primary)]">
                    {device.label}
                  </span>
                  <span className="block truncate text-xs text-[var(--lumi-text-tertiary)]">
                    {PLATFORM_LABELS[device.platform] ?? device.platform} · Vault：{device.vaultName}
                  </span>
                </span>
              </label>
            ))}
          </div>

          {/* N137：增量批注导出（水位在服务端；预览新增/修改计数）。 */}
          <label className="flex min-h-11 cursor-pointer items-center gap-2.5 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-3 py-2 text-sm">
            <input
              type="checkbox"
              checked={onlySinceLastExport}
              onChange={(e) => {
                setOnlySinceLastExport(e.target.checked)
                setIssues(null)
              }}
              className="accent-[var(--lumi-accent-text)]"
              aria-label="仅导出上次以来的批注"
            />
            <span className="min-w-0 flex-1">
              <span className="block font-medium text-[var(--lumi-text-primary)]">
                仅导出上次以来
              </span>
              <span className="block truncate text-xs text-[var(--lumi-text-tertiary)]">
                只携带上次导出之后新增 / 修改的批注
              </span>
            </span>
          </label>
          {delta.isPending ? (
            <Skeleton className="h-4 w-3/5" aria-label="增量预览加载中" />
          ) : delta.isError ? (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">
              增量预览加载失败：{delta.error.message}
            </p>
          ) : delta.data !== undefined ? (
            <p aria-live="polite" className="text-xs text-[var(--lumi-text-tertiary)]" data-lumi-export-delta="">
              {delta.data.lastExportedAt === null
                ? '这篇文章还没有导出记录（勾选增量将不带任何批注）。'
                : `上次导出之后：新增 ${delta.data.addedCount} · 修改 ${delta.data.modifiedCount}`}
            </p>
          ) : null}

          <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
            按你的导出模板组装 Markdown 后交给所选设备上的 Obsidian 打开；Lumi
            只读 Vault、绝不改写笔记，保存需要在 Obsidian 里确认。
            {policy === 'timestamp_suffix'
              ? '当前命名策略为「时间戳后缀」：重复导出会在文件名上追加 -YYYYMMDD-HHmm。'
              : '当前命名策略为「精确名」：文件按标题原样命名。'}
            注意：obsidian:// 链接无法检测 Vault 内是否已存在同名笔记（Obsidian
            官方 URI 限制），重名由命名策略缓解；文件下载路径自带唯一后缀、从不覆盖。
          </p>

          {(validate.isError || handoff.isError) && (
            <p role="alert" className="flex items-start gap-1.5 text-xs leading-relaxed text-[var(--lumi-danger)]">
              <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
              {(handoff.error ?? validate.error)?.message}
            </p>
          )}

          {/* N139：只读校验结果（用户修正后重试，或显式继续导出）。 */}
          {issues !== null && issues.length > 0 && (
            <div
              role="alert"
              data-lumi-export-issues=""
              className="flex flex-col gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2"
            >
              <p className="flex items-center gap-1.5 text-xs font-medium text-[var(--lumi-text-primary)]">
                <ListChecks aria-hidden className="size-3.5" />
                导出前校验发现 {issues.length} 个问题（仅供检查，Lumi 不会改动你的 Vault）：
              </p>
              <ul className="flex flex-col gap-1.5">
                {issues.map((issue, index) => (
                  <li key={`${issue.kind}-${index}`} className="text-xs leading-relaxed">
                    <span className="font-medium text-[var(--lumi-text-primary)]">
                      [{ISSUE_KIND_LABELS[issue.kind] ?? issue.kind}]
                    </span>{' '}
                    <span className="text-[var(--lumi-text-secondary)]">{issue.detail}</span>{' '}
                    <span className="text-[var(--lumi-text-tertiary)]">{issue.suggestion}</span>
                  </li>
                ))}
              </ul>
              <p className="text-xs text-[var(--lumi-text-tertiary)]">
                可修正后重新点「打开 Obsidian」再次校验，或选择「仍然继续导出」。
              </p>
            </div>
          )}
          {issues !== null && issues.length === 0 && (
            <p role="status" className="text-xs text-[var(--lumi-accent-text)]">
              校验通过：未发现断链或重复块 id。
            </p>
          )}

          {outcome !== null && (
            <div
              role="status"
              aria-live="polite"
              data-lumi-obsidian-outcome={outcome.kind}
              className="flex flex-col gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2"
            >
              <p className="text-xs leading-relaxed text-[var(--lumi-text-primary)]">
                {outcome.message}
              </p>
              {outcome.fallbackContent !== null && (
                <div className="flex flex-col gap-1" data-lumi-obsidian-clipboard-fallback="">
                  <textarea
                    readOnly
                    value={outcome.fallbackContent}
                    aria-label="交接内容（复制失败，可手动复制）"
                    rows={5}
                    className="w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-2 font-mono text-xs text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                  />
                  <span className="inline-flex items-center gap-1 text-[11px] text-[var(--lumi-text-tertiary)]">
                    <Clipboard aria-hidden className="size-3" />
                    自动复制失败——请全选上方内容手动复制。
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </Dialog>
  )
}
