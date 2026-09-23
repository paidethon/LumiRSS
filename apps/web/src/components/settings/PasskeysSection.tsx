/** PasskeysSection — 设置 → 账户与服务：通行密钥（N006）。
 *
 * 注册（navigator.credentials.create — 真实浏览器 API，测试中 mock）、
 * 列表（id/标签/创建/最近使用 —— 服务端契约绝不含密钥材料）、删除
 * （服务端强制当前密码；两步验证开启时还需验证码）。
 * 不支持 WebAuthn 的环境（非安全上下文等）诚实降级显示。
 */

import { useState } from 'react'
import { Fingerprint, Trash2 } from 'lucide-react'
import { ApiError, beginPasskeyRegistration, finishPasskeyRegistration } from '../../api/client'
import type { PasskeyCredential } from '../../api/client'
import { useDeletePasskeyMutation, usePasskeys } from '../../api/queries'
import {
  decodeCreationOptions,
  encodeRegistrationResponse,
  webauthnSupported,
} from '../../lib/webauthn'
import { Button } from '../ui/Button'

type Feedback = { kind: 'none' } | { kind: 'ok'; message: string } | { kind: 'error'; message: string }

function formatEpoch(epoch: number | null): string {
  if (!epoch) return '—'
  return new Date(epoch * 1000).toLocaleString()
}

export function PasskeysSection({ totpEnabled }: { totpEnabled: boolean }) {
  const passkeys = usePasskeys()
  const deleteMutation = useDeletePasskeyMutation()
  const [label, setLabel] = useState('')
  const [pending, setPending] = useState(false)
  const [feedback, setFeedback] = useState<Feedback>({ kind: 'none' })
  // 删除确认态：credential id → 当前密码（+ 两步验证码）。
  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const [deletePassword, setDeletePassword] = useState('')
  const [deleteTotp, setDeleteTotp] = useState('')
  const supported = webauthnSupported()

  async function handleRegister(event: React.FormEvent) {
    event.preventDefault()
    if (pending || !supported) return
    const trimmed = label.trim()
    if (!trimmed) {
      setFeedback({ kind: 'error', message: '请先为这把钥匙起个名字。' })
      return
    }
    setPending(true)
    setFeedback({ kind: 'none' })
    try {
      const options = await beginPasskeyRegistration()
      const credential = (await navigator.credentials.create({
        publicKey: decodeCreationOptions(options.publicKey),
      })) as PublicKeyCredential | null
      if (!credential) {
        setFeedback({ kind: 'error', message: '浏览器没有返回通行密钥。' })
        return
      }
      await finishPasskeyRegistration({
        label: trimmed,
        challenge: options.challenge,
        credential: encodeRegistrationResponse(credential),
      })
      setLabel('')
      setFeedback({ kind: 'ok', message: '通行密钥已注册。' })
    } catch (error) {
      if (error instanceof ApiError) {
        setFeedback({ kind: 'error', message: error.message })
      } else {
        // NotAllowedError 等：用户取消或设备拒绝。
        setFeedback({ kind: 'error', message: '注册未完成（可能已取消或设备拒绝）。' })
      }
    } finally {
      setPending(false)
    }
  }

  function handleDelete(row: PasskeyCredential) {
    if (!deletePassword) return
    deleteMutation.mutate(
      {
        credentialId: row.id,
        currentPassword: deletePassword,
        ...(totpEnabled && deleteTotp ? { totpCode: deleteTotp.trim() } : {}),
      },
      {
        onSuccess: () => {
          setConfirmingId(null)
          setDeletePassword('')
          setDeleteTotp('')
          setFeedback({ kind: 'ok', message: '通行密钥已删除。' })
        },
        onError: (error) => {
          setFeedback({
            kind: 'error',
            message:
              error instanceof ApiError
                ? error.message
                : '删除失败，请确认密码后重试。',
          })
        },
      },
    )
  }

  const items = passkeys.data ?? []

  return (
    <div className="mt-6 border-t border-[var(--lumi-separator)] pt-4" data-lumi-passkeys-section="">
      <div className="flex items-center gap-2">
        <Fingerprint aria-hidden className="size-4 text-[var(--lumi-text-tertiary)]" />
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">通行密钥</h3>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        通行密钥让你用本设备的屏幕锁或安全钥匙登录，无需输入密码。私钥永远不离开你的设备。
        {!supported && ' 当前浏览器环境不支持通行密钥（需要 HTTPS 或 localhost）。'}
      </p>

      <form onSubmit={handleRegister} className="mt-3 flex flex-wrap items-end gap-2" noValidate>
        <div className="min-w-40 flex-1">
          <label
            htmlFor="passkey-label"
            className="mb-1.5 block text-sm font-medium text-[var(--lumi-text-primary)]"
          >
            钥匙名称
          </label>
          <input
            id="passkey-label"
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            maxLength={64}
            disabled={pending || !supported}
            placeholder="例如：这台笔记本"
            className="min-h-10 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-sm text-[var(--lumi-text-primary)] transition-colors duration-[var(--lumi-motion-fast)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)] disabled:opacity-50"
          />
        </div>
        <Button
          type="submit"
          variant="secondary"
          size="sm"
          disabled={pending || !supported || label.trim().length === 0}
        >
          {pending ? '注册中…' : '注册通行密钥'}
        </Button>
      </form>

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

      {items.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1.5" data-lumi-passkey-list="">
          {items.map((row) => (
            <li
              key={row.id}
              className="flex flex-wrap items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-2 text-xs"
              data-lumi-passkey-row={row.id}
            >
              <span className="font-medium text-[var(--lumi-text-primary)]">{row.label || '未命名'}</span>
              <span className="text-[var(--lumi-text-tertiary)]">
                创建于 {formatEpoch(row.createdAt)} · 最近使用 {formatEpoch(row.lastUsedAt)}
              </span>
              <span className="min-w-0 flex-1" />
              {confirmingId === row.id ? (
                <span className="flex flex-wrap items-center gap-1.5">
                  <input
                    type="password"
                    autoComplete="current-password"
                    value={deletePassword}
                    onChange={(e) => setDeletePassword(e.target.value)}
                    placeholder="当前密码"
                    aria-label="确认删除：当前密码"
                    className="min-h-8 w-32 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-xs text-[var(--lumi-text-primary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)]"
                  />
                  {totpEnabled && (
                    <input
                      type="text"
                      inputMode="numeric"
                      value={deleteTotp}
                      onChange={(e) => setDeleteTotp(e.target.value)}
                      placeholder="验证码"
                      aria-label="确认删除：两步验证码"
                      className="min-h-8 w-20 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-xs text-[var(--lumi-text-primary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)]"
                    />
                  )}
                  <Button
                    size="sm"
                    variant="danger"
                    disabled={deleteMutation.isPending || deletePassword.length === 0}
                    onClick={() => handleDelete(row)}
                  >
                    确认删除
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setConfirmingId(null)
                      setDeletePassword('')
                      setDeleteTotp('')
                    }}
                  >
                    取消
                  </Button>
                </span>
              ) : (
                <Button size="sm" variant="ghost" onClick={() => setConfirmingId(row.id)}>
                  <Trash2 aria-hidden className="size-3.5" />
                  删除
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
