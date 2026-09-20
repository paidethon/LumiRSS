/** VersionUpdateToast — F117 前端版本更新确认（发现新版本）。
 *
 * App 挂载 startVersionCheck 轮询 /version.json；有新版本且未被「稍后」
 * 忽略时展示 toast：「发现新版本 [立即更新/稍后]」。
 * - 立即更新：有活跃草稿（注册表单草稿，F119）→ 先弹「有未保存草稿」
 *   保护确认（草稿本地持久，确认后刷新可恢复）；否则 location.reload；
 * - 稍后：本会话不再提示该版本；
 * - /version.json 404/网络失败 → 静默；认证 API 永不经过该机制。 */

import { useEffect, useState } from 'react'

import { APP_BUILD, applyUpdate, dismissVersion } from '../lib/version-check'
import { Button } from './ui/Button'

export default function VersionUpdateToast({
  newVersion,
  onDismiss,
  reloadFn,
}: {
  newVersion: string | null
  onDismiss?: (build: string) => void
  /** 测试接缝：确认后执行的刷新（默认 location.reload）。 */
  reloadFn?: () => void
}) {
  const doReload = reloadFn ?? ((): void => location.reload())
  const [confirmDraft, setConfirmDraft] = useState(false)

  // newVersion 变回 null（消费完/忽略）时收起保护确认
  useEffect(() => {
    if (newVersion === null) setConfirmDraft(false)
  }, [newVersion])

  if (newVersion === null) return null

  if (confirmDraft) {
    return (
      <div
        role="alertdialog"
        aria-modal="false"
        aria-label="有未保存草稿"
        data-testid="version-update-draft-guard"
        className="fixed bottom-4 left-1/2 z-[calc(var(--lumi-z-dialog)_+_1)] w-[min(94vw,26rem)] -translate-x-1/2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] p-3 shadow-[var(--lumi-shadow-dialog)]"
      >
        <p className="text-xs text-[var(--lumi-text-primary)]">
          你有未保存的草稿。草稿会保留在本机，更新后重新打开同一表单可恢复。仍要立即更新吗？
        </p>
        <div className="mt-2 flex gap-2">
          <Button
            variant="primary"
            size="sm"
            data-version-reload-confirm=""
            onClick={doReload}
          >
            保留草稿并更新
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setConfirmDraft(false)}>
            返回
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div
      role="status"
      aria-label={`发现新版本 ${newVersion}`}
      data-testid="version-update-toast"
      className="fixed bottom-4 left-1/2 z-[calc(var(--lumi-z-dialog)_+_1)] flex w-[min(94vw,26rem)] -translate-x-1/2 flex-wrap items-center gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] p-3 shadow-[var(--lumi-shadow-dialog)]"
    >
      <span className="min-w-0 flex-1 text-xs text-[var(--lumi-text-primary)]">
        发现新版本（当前 {APP_BUILD} → 新 {newVersion}）
      </span>
      <Button
        variant="primary"
        size="sm"
        data-version-update=""
        onClick={() => {
          const outcome = applyUpdate(doReload)
          if (outcome === 'confirm-draft') setConfirmDraft(true)
        }}
      >
        立即更新
      </Button>
      <Button
        variant="ghost"
        size="sm"
        data-version-dismiss=""
        onClick={() => {
          dismissVersion(newVersion)
          onDismiss?.(newVersion)
        }}
      >
        稍后
      </Button>
    </div>
  )
}
