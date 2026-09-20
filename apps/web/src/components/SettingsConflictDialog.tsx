/** SettingsConflictDialog — F116 设置冲突解决界面。
 *
 * settings-sync 遇到 409 时（不再静默 rehydrate）登记冲突快照，本对话
 * 按字段列出 本地候选 vs 服务端当前；逐字段选择（默认服务端）→
 * 「提交所选」组装 PATCH；再次冲突 → 快照刷新、对话框保持再选；
 * 取消 → 采用服务端（本地未选字段丢弃——文案明确警示）；网络失败
 * → 对话框保留（不静默丢）。 */

import { useMemo, useState } from 'react'
import { createPortal } from 'react-dom'

import { Button } from './ui/Button'
import {
  discardSettingsConflict,
  resolveSettingsConflict,
  useSettingsConflict,
} from '../store/settings-conflict'
import { PORTABLE_KEYS } from '../store/app-settings'

const FIELD_LABELS: Record<string, string> = {
  themeMode: '主题模式',
  accentColor: '强调色',
  readerFontSize: '正文字号',
  readerLineHeight: '行高',
  readerBackground: '阅读背景',
  listDensity: '列表密度',
  timelineOrder: '时间线排序',
}

export default function SettingsConflictDialog() {
  const conflict = useSettingsConflict((s) => s.conflict)
  // 每字段选择：true = 采用本地候选；false = 采用服务端（默认）
  const [localChoices, setLocalChoices] = useState<Record<string, boolean>>({})
  const [status, setStatus] = useState<'idle' | 'submitting' | 'error'>('idle')

  const keys = useMemo(() => {
    if (conflict === null) return []
    const known = new Set<string>(PORTABLE_KEYS as readonly string[])
    return [
      ...Object.keys(conflict.localPending ?? {}),
      ...Object.keys(conflict.serverState ?? {}),
    ].filter(
      (key, index, all) =>
        all.indexOf(key) === index &&
        key !== 'schemaVersion' &&
        key !== 'revision' &&
        (known.has(key) || key in (conflict.localPending ?? {})),
    )
  }, [conflict])

  if (conflict === null) return null

  const fmt = (value: unknown): string => {
    if (value === undefined || value === null) return '（空）'
    if (typeof value === 'object') {
      try {
        return JSON.stringify(value)
      } catch {
        return String(value)
      }
    }
    return String(value)
  }

  const submit = async () => {
    setStatus('submitting')
    const chosen = keys.filter((key) => localChoices[key] === true)
    const outcome = await resolveSettingsConflict(chosen)
    if (outcome === 'resolved') {
      setStatus('idle')
      return // conflict 已清除 → 对话框卸载
    }
    // conflict-again：快照已刷新 → 保留对话框再选；network-error：保留不丢
    setStatus(outcome === 'network-error' ? 'error' : 'idle')
  }

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="解决设置冲突"
      data-testid="settings-conflict-dialog"
      className="fixed inset-0 z-[calc(var(--lumi-z-dialog)_+_2)] flex items-center justify-center px-4"
    >
      <button
        type="button"
        aria-label="关闭冲突对话框"
        onClick={() => discardSettingsConflict()}
        className="absolute inset-0 size-full cursor-default bg-[var(--lumi-text-primary)]/30"
      />
      <div className="relative flex max-h-[80dvh] w-[min(94vw,34rem)] flex-col overflow-hidden rounded-[var(--lumi-radius-xl)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] shadow-[var(--lumi-shadow-dialog)]">
        <div className="border-b border-[var(--lumi-separator)] px-4 py-3">
          <h2 className="text-sm font-semibold text-[var(--lumi-text-primary)]">
            设置冲突：其他设备修改了这些设置
          </h2>
          <p className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">
            请逐字段选择要采用的值（默认采用服务端当前值）。取消 = 全部采用服务端，未选中的本地修改将被丢弃。
          </p>
        </div>
        <ul className="min-h-0 flex-1 divide-y divide-[var(--lumi-separator)] overflow-y-auto px-4">
          {keys.map((key) => (
            <li key={key} className="flex items-center justify-between gap-3 py-2.5" data-conflict-field={key}>
              <div className="min-w-0 text-xs">
                <div className="font-medium text-[var(--lumi-text-primary)]">
                  {FIELD_LABELS[key] ?? key}
                </div>
                <div className="mt-0.5 flex flex-wrap gap-x-3 text-[var(--lumi-text-tertiary)]">
                  <span data-conflict-local={key}>
                    本地：{fmt(conflict.localPending?.[key])}
                  </span>
                  <span data-conflict-server={key}>
                    服务端：{fmt(conflict.serverState?.[key])}
                  </span>
                </div>
              </div>
              <label className="flex shrink-0 items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]">
                <input
                  type="checkbox"
                  aria-label={`采用本地值：${FIELD_LABELS[key] ?? key}`}
                  data-conflict-choose={key}
                  checked={localChoices[key] === true}
                  onChange={(event) =>
                    setLocalChoices((prev) => ({ ...prev, [key]: event.target.checked }))
                  }
                  className="size-4 accent-[var(--lumi-accent)]"
                />
                用本地
              </label>
            </li>
          ))}
        </ul>
        <div className="flex items-center gap-2 border-t border-[var(--lumi-separator)] px-4 py-3">
          <Button variant="primary" size="sm" disabled={status === 'submitting'} onClick={() => void submit()} data-conflict-submit="">
            {status === 'submitting' ? '提交中…' : '提交所选'}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => discardSettingsConflict()}
            data-conflict-cancel=""
          >
            取消（采用服务端）
          </Button>
          {status === 'error' ? (
            <span role="alert" className="text-xs text-[var(--lumi-danger-text, #b3261e)]">
              提交失败（网络）；对话框已保留，稍后可重试。
            </span>
          ) : null}
        </div>
      </div>
    </div>,
    document.body,
  )
}
