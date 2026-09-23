/** ObsidianExportDialog — P16「导出到 Obsidian」交接对话框。
 *
 * 流程：选一个设备档案（GET /obsidian/devices）→ POST export-handoff
 * （服务端按模板渲染并裁决 uri / file）→ runObsidianHandoff 执行：
 * - mode='uri'：跳官方 obsidian://new 链接，文案「已打开 Obsidian（请在
 *   Obsidian 确认保存）」—— 诚实交接：Lumi 不写 Vault（ADR 0004），
 *   保存由用户在 Obsidian 确认；绝不显示「已写入」。
 * - mode='file'（tooLong）：下载 .md + 剪贴板，文案如实说明走了哪条路。
 * 复制失败 → 只读文本框诚实降级。无设备档案 → 空态引导去设置。 */

import { useState } from 'react'
import { AlertCircle, BookMarked, Clipboard } from 'lucide-react'
import type { EntryDetail } from '../api/types'
import { useObsidianDevices, useObsidianExportHandoffMutation } from '../api/queries'
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
  const handoff = useObsidianExportHandoffMutation()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<HandoffOutcome | null>(null)

  const items = devices.data?.items ?? []
  const effectiveId =
    selectedId !== null && items.some((d) => d.id === selectedId)
      ? selectedId
      : (items[0]?.id ?? null)

  const run = () => {
    if (effectiveId === null || handoff.isPending) return
    setOutcome(null)
    handoff.mutate(
      { entryRef: detail.entryRef, deviceId: effectiveId },
      {
        onSuccess: async (result) => {
          setOutcome(await runObsidianHandoff(result))
        },
      },
    )
  }

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
            disabled={effectiveId === null || handoff.isPending}
            onClick={run}
          >
            <BookMarked aria-hidden className="size-3.5" />
            {handoff.isPending ? '准备中…' : '打开 Obsidian'}
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
                  onChange={() => setSelectedId(device.id)}
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

          <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
            按你的导出模板组装 Markdown 后交给所选设备上的 Obsidian 打开；Lumi
            只读 Vault、绝不改写笔记，保存需要在 Obsidian 里确认。
          </p>

          {handoff.isError && (
            <p role="alert" className="flex items-start gap-1.5 text-xs leading-relaxed text-[var(--lumi-danger)]">
              <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
              {handoff.error.message}
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
