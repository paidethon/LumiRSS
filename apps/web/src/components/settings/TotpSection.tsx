/** TotpSection — 设置 → 账户与服务：两步验证（N007）。
 *
 * - 未开启：setup（服务端生成秘密，otpauth URI + 秘密明文只显示一次，
 *   手动录入认证器 —— 不引入 QR 渲染依赖）→ 输入 6 位验证码 enable →
 *   恢复码明文只显示一次（需勾选「已保存」才消失）。
 * - 已开启：显示剩余恢复码数量 + 关闭表单（密码 + 验证码/恢复码，
 *   服务端强制，前端只是收集输入）。
 */

import { useState } from 'react'
import { ShieldCheck } from 'lucide-react'
import { ApiError } from '../../api/client'
import {
  useTotpDisableMutation,
  useTotpEnableMutation,
  useTotpSetupMutation,
  useTotpStatus,
} from '../../api/queries'
import { Button } from '../ui/Button'

type Feedback = { kind: 'none' } | { kind: 'ok'; message: string } | { kind: 'error'; message: string }

function CopyLine({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="flex items-start gap-2">
      <div className="min-w-0 flex-1">
        <span className="block text-xs font-medium text-[var(--lumi-text-primary)]">{label}</span>
        <code className="mt-0.5 block max-h-20 overflow-y-auto break-all font-mono text-[11px] text-[var(--lumi-text-secondary)]" data-lumi-copy-target="">
          {value}
        </code>
      </div>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(value)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          } catch {
            // 剪贴板不可用（非安全上下文）：静默失败，文本仍可见可手动复制。
          }
        }}
      >
        {copied ? '已复制' : '复制'}
      </Button>
    </div>
  )
}

export function TotpSection() {
  const status = useTotpStatusSafe()
  const setupMutation = useTotpSetupMutation()
  const enableMutation = useTotpEnableMutation()
  const disableMutation = useTotpDisableMutation()

  const [setupSecret, setSetupSecret] = useState<{ secret: string; otpauthUri: string } | null>(null)
  const [code, setCode] = useState('')
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null)
  const [recoverySaved, setRecoverySaved] = useState(false)
  const [disablePassword, setDisablePassword] = useState('')
  const [disableCode, setDisableCode] = useState('')
  const [feedback, setFeedback] = useState<Feedback>({ kind: 'none' })

  const enabled = status?.enabled ?? false

  async function handleSetup() {
    setFeedback({ kind: 'none' })
    try {
      const view = await setupMutation.mutateAsync()
      setSetupSecret(view)
    } catch (error) {
      setFeedback({ kind: 'error', message: error instanceof ApiError ? error.message : '设置失败，请稍后重试。' })
    }
  }

  async function handleEnable(event: React.FormEvent) {
    event.preventDefault()
    if (!setupSecret || code.trim().length !== 6) return
    setFeedback({ kind: 'none' })
    try {
      const result = await enableMutation.mutateAsync(code.trim())
      setRecoveryCodes(result.recoveryCodes)
      setSetupSecret(null)
      setCode('')
    } catch (error) {
      setFeedback({ kind: 'error', message: error instanceof ApiError ? error.message : '开启失败，请重试。' })
    }
  }

  async function handleDisable(event: React.FormEvent) {
    event.preventDefault()
    if (!disablePassword || !disableCode.trim()) return
    setFeedback({ kind: 'none' })
    try {
      await disableMutation.mutateAsync({ code: disableCode.trim(), currentPassword: disablePassword })
      setDisablePassword('')
      setDisableCode('')
      setFeedback({ kind: 'ok', message: '两步验证已关闭。' })
    } catch (error) {
      setFeedback({ kind: 'error', message: error instanceof ApiError ? error.message : '关闭失败，请重试。' })
    }
  }

  if (status === null) return null // basic 模式 / 查询失败：诚实不渲染

  return (
    <div className="mt-6 border-t border-[var(--lumi-separator)] pt-4" data-lumi-totp-section="">
      <div className="flex items-center gap-2">
        <ShieldCheck aria-hidden className="size-4 text-[var(--lumi-text-tertiary)]" />
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">两步验证</h3>
        <span
          className={
            enabled
              ? 'rounded-[var(--lumi-radius-full)] bg-[var(--lumi-accent-soft)] px-2 py-0.5 text-[11px] text-[var(--lumi-accent-text)]'
              : 'rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-2)] px-2 py-0.5 text-[11px] text-[var(--lumi-text-tertiary)]'
          }
        >
          {enabled ? '已开启' : '未开启'}
        </span>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        开启后，密码登录需要再输入认证器生成的 6 位验证码。验证码与恢复码只经加密传输发送，不会保存在浏览器中。
      </p>

      {!enabled && !setupSecret && (
        <div className="mt-3">
          <Button type="button" variant="secondary" size="sm" onClick={handleSetup} disabled={setupMutation.isPending}>
            {setupMutation.isPending ? '生成中…' : '开启两步验证'}
          </Button>
        </div>
      )}

      {setupSecret && (
        <div className="mt-3 flex flex-col gap-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3">
          <p className="text-xs text-[var(--lumi-text-secondary)]">
            在认证器 App（如 Google Authenticator、1Password）中选择「手动录入」，粘贴以下密钥或 URI：
          </p>
          <CopyLine label="密钥（Base32）" value={setupSecret.secret} />
          <CopyLine label="otpauth URI" value={setupSecret.otpauthUri} />
          <form onSubmit={handleEnable} className="flex flex-wrap items-end gap-2" noValidate>
            <div>
              <label htmlFor="totp-enable-code" className="mb-1.5 block text-sm font-medium text-[var(--lumi-text-primary)]">
                输入 6 位验证码确认
              </label>
              <input
                id="totp-enable-code"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                disabled={enableMutation.isPending}
                className="min-h-10 w-32 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 font-mono text-sm tracking-widest text-[var(--lumi-text-primary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)] disabled:opacity-50"
              />
            </div>
            <Button type="submit" variant="primary" size="sm" disabled={enableMutation.isPending || code.length !== 6}>
              {enableMutation.isPending ? '验证中…' : '确认开启'}
            </Button>
          </form>
        </div>
      )}

      {recoveryCodes && (
        <div className="mt-3 flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3" data-lumi-recovery-codes="">
          <p className="text-xs font-medium text-[var(--lumi-text-primary)]">
            恢复码（仅显示这一次 —— 请立即保存到安全的地方）
          </p>
          <ul className="grid grid-cols-2 gap-1 sm:grid-cols-4">
            {recoveryCodes.map((recovery) => (
              <li key={recovery} className="rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-2)] px-2 py-1 font-mono text-xs text-[var(--lumi-text-primary)]">
                {recovery}
              </li>
            ))}
          </ul>
          <label className="flex items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
            <input
              type="checkbox"
              checked={recoverySaved}
              onChange={(e) => setRecoverySaved(e.target.checked)}
              className="size-4 accent-[var(--lumi-accent)]"
            />
            我已保存这些恢复码（丢失认证器时可用于登录）
          </label>
          <div>
            <Button type="button" variant="secondary" size="sm" disabled={!recoverySaved} onClick={() => setRecoveryCodes(null)}>
              完成
            </Button>
          </div>
        </div>
      )}

      {enabled && (
        <form onSubmit={handleDisable} className="mt-3 flex flex-wrap items-end gap-2" noValidate data-lumi-totp-disable="">
          <div>
            <label htmlFor="totp-disable-password" className="mb-1.5 block text-sm font-medium text-[var(--lumi-text-primary)]">
              当前登录密码
            </label>
            <input
              id="totp-disable-password"
              type="password"
              autoComplete="current-password"
              value={disablePassword}
              onChange={(e) => setDisablePassword(e.target.value)}
              disabled={disableMutation.isPending}
              className="min-h-10 w-40 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-sm text-[var(--lumi-text-primary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)] disabled:opacity-50"
            />
          </div>
          <div>
            <label htmlFor="totp-disable-code" className="mb-1.5 block text-sm font-medium text-[var(--lumi-text-primary)]">
              验证码或恢复码
            </label>
            <input
              id="totp-disable-code"
              type="text"
              value={disableCode}
              onChange={(e) => setDisableCode(e.target.value)}
              disabled={disableMutation.isPending}
              className="min-h-10 w-32 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 font-mono text-sm text-[var(--lumi-text-primary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)] disabled:opacity-50"
            />
          </div>
          <Button type="submit" variant="danger" size="sm" disabled={disableMutation.isPending || !disablePassword || !disableCode.trim()}>
            {disableMutation.isPending ? '关闭中…' : '关闭两步验证'}
          </Button>
          {status.recoveryCodesRemaining > 0 && (
            <span className="text-xs text-[var(--lumi-text-tertiary)]">剩余恢复码：{status.recoveryCodesRemaining}</span>
          )}
        </form>
      )}

      {feedback.kind !== 'none' && (
        <p
          role="alert"
          aria-live="polite"
          className={
            feedback.kind === 'ok'
              ? 'mt-2 text-xs text-[var(--lumi-accent-text)]'
              : 'mt-2 text-xs text-[var(--lumi-danger)]'
          }
        >
          {feedback.message}
        </p>
      )}
    </div>
  )
}

/** TOTP 状态查询（容错）：basic 模式 401 → null（不渲染）。 */
function useTotpStatusSafe(): { enabled: boolean; recoveryCodesRemaining: number } | null {
  const query = useTotpStatus()
  if (query.isPending || query.isError) return null
  return query.data
}
