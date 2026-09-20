/** StorageRetentionSection — F114：派生数据保留策略（默认关）。
 *
 * 两类可清理：AI 摘要历史版本（30–365 天）、任务日志（7–180 天）；
 * 保护类（entries/annotations/notes/cards/credentials/运行中任务）
 * 服务端永不清理，预览如实列出。流程 = 配置 → 保存 → 预览（只读）
 * → 应用（有界删除，需先看过预览——武装确认）。 */

import { useState } from 'react'

import { ApiError } from '../../api/client'
import type { RetentionApplyResult, RetentionPreview } from '../../api/client'
import {
  useRetentionApplyMutation,
  useRetentionPreviewMutation,
  useSaveStorageRetentionMutation,
  useStorageRetention,
} from '../../api/queries'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/Skeleton'
import { Switch } from '../ui/Switch'

function fmtBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function clampOrNull(value: string, low: number, high: number): number | null {
  const parsed = Number.parseInt(value, 10)
  if (Number.isNaN(parsed) || parsed < low || parsed > high) return null
  return parsed
}

export function StorageRetentionSection() {
  const retention = useStorageRetention()
  const save = useSaveStorageRetentionMutation()
  const preview = useRetentionPreviewMutation()
  const apply = useRetentionApplyMutation()

  const [aiVersionsDays, setAiVersionsDays] = useState<string>('')
  const [taskLogDays, setTaskLogDays] = useState<string>('')
  const [saveError, setSaveError] = useState<string | null>(null)
  const [previewSeen, setPreviewSeen] = useState(false)
  const [applyResult, setApplyResult] = useState<RetentionApplyResult | null>(null)

  if (retention.isPending) {
    return (
      <div className="py-3" aria-label="保留策略加载中">
        <Skeleton className="h-11 w-full" />
      </div>
    )
  }
  if (retention.isError) {
    return (
      <p className="py-3 text-xs text-[var(--lumi-text-tertiary)]">
        保留策略加载失败：{retention.error instanceof Error ? retention.error.message : '请稍后重试。'}
      </p>
    )
  }

  const config = retention.data
  const currentAiDays = aiVersionsDays === '' ? (config.aiVersionsDays ?? '') : aiVersionsDays
  const currentLogDays = taskLogDays === '' ? (config.taskLogDays ?? '') : taskLogDays

  const saveConfig = (enabled: boolean) => {
    setSaveError(null)
    // 保留天数与开关独立提交：关着也能保存用户填的天数（服务端各自收敛）
    save.mutate(
      {
        enabled,
        aiVersionsDays: clampOrNull(String(currentAiDays), 30, 365),
        taskLogDays: clampOrNull(String(currentLogDays), 7, 180),
      },
      { onError: (error) => setSaveError(error instanceof ApiError ? error.message : '保存失败。') },
    )
  }

  const previewData: RetentionPreview | undefined = preview.data

  return (
    <div className="py-3" data-storage-retention="">
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-medium text-[var(--lumi-text-primary)]">派生数据保留策略</div>
        <Switch
          id="storage-retention-enabled"
          label="启用保留策略"
          checked={config.enabled}
          onCheckedChange={(checked) => saveConfig(checked)}
        />
      </div>
      <p className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">
        默认关闭。启用后按「天」清理派生数据（AI 摘要历史版本 / 任务日志）；文章、批注、笔记、卡片、凭据与运行中任务永不清理。
      </p>

      <div className="mt-2 flex flex-wrap items-center gap-3 text-xs">
        <label className="flex items-center gap-1.5">
          <span className="text-[var(--lumi-text-secondary)]">AI 历史版本保留（30–365 天，留空 = 不清理该类）</span>
          <input
            type="number"
            min={30}
            max={365}
            aria-label="AI 历史版本保留天数"
            value={currentAiDays}
            onChange={(event) => setAiVersionsDays(event.target.value)}
            className="min-h-8 w-20 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5"
          />
        </label>
        <label className="flex items-center gap-1.5">
          <span className="text-[var(--lumi-text-secondary)]">任务日志保留（7–180 天，留空 = 不清理该类）</span>
          <input
            type="number"
            min={7}
            max={180}
            aria-label="任务日志保留天数"
            value={currentLogDays}
            onChange={(event) => setTaskLogDays(event.target.value)}
            className="min-h-8 w-20 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5"
          />
        </label>
        <Button
          variant="secondary"
          size="sm"
          data-retention-save=""
          disabled={save.isPending}
          onClick={() => saveConfig(config.enabled)}
        >
          {save.isPending ? '保存中…' : '保存配置'}
        </Button>
      </div>
      {saveError ? <p role="alert" className="mt-1 text-xs text-[var(--lumi-danger)]">{saveError}</p> : null}

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button
          variant="secondary"
          size="sm"
          data-retention-preview=""
          disabled={preview.isPending}
          onClick={() => {
            setPreviewSeen(true)
            setApplyResult(null)
            preview.mutate()
          }}
        >
          {preview.isPending ? '预览中…' : '预览将清理的内容'}
        </Button>
        <Button
          variant="danger"
          size="sm"
          data-retention-apply=""
          disabled={!previewSeen || apply.isPending || !config.enabled}
          title={previewSeen ? undefined : '请先预览'}
          onClick={() =>
            apply.mutate(undefined, { onSuccess: (data) => setApplyResult(data) })
          }
        >
          {apply.isPending ? '清理中…' : '应用清理'}
        </Button>
      </div>
      {!config.enabled && (
        <p className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">策略未启用时「应用」为 no-op。</p>
      )}

      {preview.isError && (
        <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">
          预览失败：{preview.error instanceof Error ? preview.error.message : '请稍后重试。'}
        </p>
      )}
      {previewData && (
        <div className="mt-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-2.5 text-xs" data-retention-preview-result="">
          <p className="text-[var(--lumi-text-secondary)]">
            {previewData.enabled
              ? `将清理：AI 历史版本 ${previewData.aiVersions.count} 条（约 ${fmtBytes(previewData.aiVersions.bytes)}）；任务日志 ${previewData.taskLog.count} 条。`
              : '策略未启用：预览为零（不清理任何内容）。'}
          </p>
          <p className="mt-0.5 text-[var(--lumi-text-tertiary)]">
            保护不清理：文章 / 批注 / 笔记 / 卡片 / 凭据 / 运行中任务；{previewData.quizNote}
          </p>
        </div>
      )}
      {apply.isError && (
        <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">
          清理失败：{apply.error instanceof Error ? apply.error.message : '请稍后重试。'}
        </p>
      )}
      {applyResult && (
        <p role="status" className="mt-2 text-xs text-[var(--lumi-text-secondary)]" data-retention-apply-result="">
          {applyResult.enabled
            ? `已清理：AI 历史版本 ${applyResult.deleted.aiVersions} 条，任务日志 ${applyResult.deleted.taskLog} 条（有界执行，可重复应用）。`
            : (applyResult.note ?? '策略未启用：本次为 no-op。')}
        </p>
      )}
    </div>
  )
}
