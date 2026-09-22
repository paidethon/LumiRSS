/** LoginScreen — 多账户会话登录页（LUMIRSS_AUTH_MODE=session）。
 *
 * username + password（0067 多账户）。成功后浏览器持有
 * Secure/HttpOnly Cookie，本组件不保存任何凭据；身份（username/role）
 * 由登录后的 GET /auth/session 服务端核实，绝不取自响应体之外。
 *
 * 错误语义（Phase O + 0067 契约）：
 * - invalid_credentials → 统一「用户名或密码不正确」——不区分
 *   「用户不存在/密码错误」（O171 无账号枚举预言机）；
 * - rate_limited → 显示 Retry-After 的剩余等待秒数；
 * - 网络不可用 → 「网络不可用」，绝不显示「密码错误 / 会话过期」。
 *
 * O157：登录成功先 resetAccountState 清上一账号的本地足迹与缓存，
 * 再翻认证门——换账号绝不串号。basic 模式永远到不了本页
 * （AuthGate 对 mode=basic 直接放行）。
 */

import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Eye, EyeOff, LogIn } from 'lucide-react'
import { ApiError, getAuthSession, loginAccount } from '../api/client'
import { identityFromSession, useAuthStore } from '../store/auth'
import { resetAccountState } from '../lib/auth-reset'
import { navigateAppRoute, readAppRoute } from '../lib/app-route'
import { Button } from './ui/Button'

type LoginFeedback =
  | { kind: 'none' }
  | { kind: 'error'; message: string }
  | { kind: 'offline'; message: string }

/** invalid_credentials 的统一文案——错误身份不透露哪个字段错了。 */
const INVALID_CREDENTIALS_TEXT = '用户名或密码不正确。'

function rateLimitedText(retryAfterSeconds: number | null): string {
  if (retryAfterSeconds !== null && retryAfterSeconds > 0) {
    return `尝试过于频繁，请约 ${retryAfterSeconds} 秒后再试。`
  }
  return '尝试过于频繁，请稍后再试。'
}

export default function LoginScreen() {
  const queryClient = useQueryClient()
  const setStatus = useAuthStore((s) => s.setStatus)
  const [username, setUsername] = useState('')
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
    if (pending || password.length === 0 || username.trim().length === 0) return
    setPending(true)
    setFeedback({ kind: 'none' })
    try {
      const status = await loginAccount(username.trim(), password)
      if (status.authenticated) {
        // 身份由服务端核实（login 响应只含 authenticated）；探测失败
        // 不阻断进入——identity 为 null 时账号菜单隐藏，session 过期
        // 仍会正常翻门。
        let identity = null
        try {
          identity = identityFromSession(await getAuthSession())
        } catch {
          identity = null
        }
        // O157：先清上一账号状态（缓存/草稿/最近阅读…），再进门。
        resetAccountState(queryClient)
        useAuthStore.getState().setIdentity(identity)
        // 会话过期可能把用户留在 /admin、/activate 等路径：登录成功
        // 回到应用主路由（replace，不留登录前残迹在历史里）。
        if (readAppRoute() !== 'app') navigateAppRoute('app', true)
        setPassword('')
        setStatus('authenticated')
      }
    } catch (error) {
      if (error instanceof ApiError && error.type === 'network_error') {
        setFeedback({
          kind: 'offline',
          message: '网络不可用 —— 请检查网络连接后重试。',
        })
      } else if (error instanceof ApiError && error.type === 'invalid_credentials') {
        // 统一文案：不区分用户不存在/密码错误（无账号枚举）。
        setFeedback({ kind: 'error', message: INVALID_CREDENTIALS_TEXT })
      } else if (error instanceof ApiError && error.type === 'rate_limited') {
        setFeedback({
          kind: 'error',
          message: rateLimitedText(error.retryAfterSeconds),
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
              流光阅源 · 登录继续
            </p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3" noValidate>
          <div>
            <label
              htmlFor="login-username"
              className="mb-1.5 block text-sm font-medium text-[var(--lumi-text-primary)]"
            >
              用户名
            </label>
            <input
              id="login-username"
              ref={inputRef}
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              enterKeyHint="next"
              inputMode="text"
              disabled={pending}
              aria-invalid={feedback.kind !== 'none' || undefined}
              aria-describedby={feedback.kind !== 'none' ? 'login-feedback' : undefined}
              className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-base text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:border-[var(--lumi-text-tertiary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)] disabled:opacity-50"
              placeholder="用户名"
            />
          </div>

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
            disabled={pending || password.length === 0 || username.trim().length === 0}
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
