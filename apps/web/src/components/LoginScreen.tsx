/** LoginScreen — 单用户会话登录页（LUMIRSS_AUTH_MODE=session）。
 *
 * 只输密码（单用户，username 无产品价值）。成功后浏览器持有
 * Secure/HttpOnly Cookie，本组件不保存任何凭据。
 *
 * 错误语义（Phase O 契约）：
 * - 密码错误 / 未初始化 / 限流 → 服务端明确错误信息；
 * - 网络不可用 → 「网络不可用」，绝不显示「密码错误 / 会话过期」。
 */

import { useEffect, useRef, useState } from 'react'
import { Eye, EyeOff, LogIn } from 'lucide-react'
import { ApiError, loginPassword } from '../api/client'
import { useAuthStore } from '../store/auth'
import { Button } from './ui/Button'

type LoginFeedback =
  | { kind: 'none' }
  | { kind: 'error'; message: string }
  | { kind: 'offline'; message: string }

export default function LoginScreen() {
  const setStatus = useAuthStore((s) => s.setStatus)
  const [password, setPassword] = useState('')
  const [reveal, setReveal] = useState(false)
  const [pending, setPending] = useState(false)
  const [feedback, setFeedback] = useState<LoginFeedback>({ kind: 'none' })
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // 离线状态变化时清除误导性的「密码错误」提示（Phase O：离线 ≠ 未登录）。
  useEffect(() => {
    const goOnline = () => setFeedback({ kind: 'none' })
    window.addEventListener('online', goOnline)
    return () => window.removeEventListener('online', goOnline)
  }, [])

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (pending || password.length === 0) return
    setPending(true)
    setFeedback({ kind: 'none' })
    try {
      const status = await loginPassword(password)
      if (status.authenticated) {
        setPassword('')
        setStatus('authenticated')
      }
    } catch (error) {
      if (error instanceof ApiError && error.type === 'network_error') {
        setFeedback({
          kind: 'offline',
          message: '网络不可用 —— 请检查网络连接后重试。',
        })
      } else if (error instanceof ApiError) {
        setFeedback({ kind: 'error', message: error.message })
      } else {
        setFeedback({ kind: 'error', message: '登录失败，请稍后重试。' })
      }
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-[var(--lumi-canvas)] px-6 py-[max(1.5rem,env(safe-area-inset-top))] pb-[max(1.5rem,env(safe-area-inset-bottom))]">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <img src="/icons/lumirss-icon.svg" alt="" className="size-14" decoding="async" />
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-[var(--lumi-text-primary)]">
              LumiRSS
            </h1>
            <p className="mt-1 text-sm text-[var(--lumi-text-secondary)]">
              流光阅源 · 输入密码继续
            </p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3" noValidate>
          <div>
            <label
              htmlFor="login-password"
              className="mb-1.5 block text-sm font-medium text-[var(--lumi-text-primary)]"
            >
              密码
            </label>
            <div className="relative">
              <input
                id="login-password"
                ref={inputRef}
                type={reveal ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                enterKeyHint="go"
                inputMode="text"
                disabled={pending}
                aria-invalid={feedback.kind !== 'none' || undefined}
                aria-describedby={feedback.kind !== 'none' ? 'login-feedback' : undefined}
                className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 pr-11 text-base text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:border-[var(--lumi-text-tertiary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)] disabled:opacity-50"
                placeholder="••••••••"
              />
              <button
                type="button"
                onClick={() => setReveal((v) => !v)}
                aria-label={reveal ? '隐藏密码' : '显示密码'}
                className="absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
              >
                {reveal ? (
                  <EyeOff aria-hidden className="size-4" />
                ) : (
                  <Eye aria-hidden className="size-4" />
                )}
              </button>
            </div>
          </div>

          {feedback.kind !== 'none' && (
            <p
              id="login-feedback"
              role="alert"
              aria-live="polite"
              className={
                feedback.kind === 'offline'
                  ? 'text-xs leading-relaxed text-[var(--lumi-text-secondary)]'
                  : 'text-xs leading-relaxed text-[var(--lumi-danger)]'
              }
            >
              {feedback.message}
            </p>
          )}

          <Button
            type="submit"
            variant="primary"
            size="md"
            disabled={pending || password.length === 0}
            className="min-h-11 w-full"
          >
            <LogIn aria-hidden className="size-4" />
            {pending ? '登录中…' : '登录'}
          </Button>

          <p className="mt-1 text-center text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
            登录后在此设备保持登录，无需反复输入密码。
          </p>
        </form>
      </div>
    </div>
  )
}
