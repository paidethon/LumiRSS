/** LoginScreen — 多账户会话登录页（LUMIRSS_AUTH_MODE=session）。
 *
 * username + password（0067 多账户）。成功后浏览器持有
 * Secure/HttpOnly Cookie，本组件不保存任何凭据；身份（username/role）
 * 由登录后的 GET /auth/session 服务端核实，绝不取自响应体之外。
 *
 * N006 通行密钥：输入用户名后（防抖查询 login-options），仅当服务端
 * 回报该用户名下有已注册通行密钥时显示「使用通行密钥」；走真实
 * navigator.credentials.get（测试中 mock），成功后与密码登录同一
 * 会话流程。
 *
 * N007 两步验证：账号开启 TOTP 时，密码正确返回 {totpRequired,
 * pendingToken}（短时效非会话）→ 显示验证码输入（可切换恢复码）→
 * /auth/totp/verify 换发真会话。
 *
 * 错误语义（Phase O + 0067 契约）：
 * - invalid_credentials → 统一「用户名或密码不正确」——不区分
 *   「用户不存在/密码错误」（O171 无账号枚举预言机）；通行密钥
 *   登录失败同样使用统一文案（断言验证失败不泄露细节）；
 * - rate_limited → 显示 Retry-After 的剩余等待秒数；
 * - 网络不可用 → 「网络不可用」，绝不显示「密码错误 / 会话过期」。
 *
 * O157：登录成功先 resetAccountState 清上一账号的本地足迹与缓存，
 * 再翻认证门——换账号绝不串号。basic 模式永远到不了本页
 * （AuthGate 对 mode=basic 直接放行）。
 *
 * F015 认证前目标：登录前 URL 带 ?next=/path（同源路径，经
 * isSafeAuthRedirectPath 校验：单 / 开头、禁 //、禁 scheme）时，登录
 * 成功后回到该目标；非法或缺失回退应用首页。注册/激活入口在下方
 * 链接（/register、/activate 同属未认证顶层页）。
 */

import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Eye, EyeOff, Fingerprint, LogIn, UserPlus } from 'lucide-react'
import {
  ApiError,
  beginPasskeyLogin,
  finishPasskeyLogin,
  getAuthSession,
  isTotpChallenge,
  loginAccount,
  verifyTotpLogin,
} from '../api/client'
import { identityFromSession, useAuthStore } from '../store/auth'
import { resetAccountState } from '../lib/auth-reset'
import {
  isSafeAuthRedirectPath,
  navigateAppRoute,
  navigateToPath,
  readAppRoute,
  readAuthRedirectTarget,
} from '../lib/app-route'
import {
  decodeRequestOptions,
  encodeAssertionResponse,
  webauthnSupported,
} from '../lib/webauthn'
import { Button } from './ui/Button'

type LoginFeedback =
  | { kind: 'none' }
  | { kind: 'error'; message: string }
  | { kind: 'offline'; message: string }
  /** N190：账户已停用 —— 诚实状态页（计划删除时间 + 恢复/迁出指引）。 */
  | { kind: 'deactivated'; message: string; scheduledDeletionAt: string | null }
  /** N190：账户已停用 —— 诚实的状态页（含计划删除时间与恢复途径）。 */
  | {
      kind: 'deactivated'
      message: string
      scheduledDeletionAt: string | null
    }

/** invalid_credentials 的统一文案——错误身份不透露哪个字段错了。 */
const INVALID_CREDENTIALS_TEXT = '用户名或密码不正确。'
/** 通行密钥断言失败与密码错误同形（不泄露是挑战/签名/凭据哪一环）。 */
const PASSKEY_FAILED_TEXT = '通行密钥验证失败。'
const TOTP_INVALID_TEXT = '验证码无效。'

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
  // N006：服务端确认「该用户名可用通行密钥」后才显示入口。
  const [passkeyAvailable, setPasskeyAvailable] = useState(false)
  // N007：两步验证阶段（pendingToken 来自密码步）。
  const [totpPendingToken, setTotpPendingToken] = useState<string | null>(null)
  const [totpCode, setTotpCode] = useState('')
  const [totpUseRecovery, setTotpUseRecovery] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const passkeyProbeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // 离线状态变化时清除误导性的「密码错误」提示（Phase O：离线 ≠ 未登录）。
  useEffect(() => {
    const goOnline = () => setFeedback({ kind: 'none' })
    window.addEventListener('online', goOnline)
    return () => window.removeEventListener('online', goOnline)
  }, [])

  // N006：用户名变化后防抖探测（服务端对未知用户名返回诚实通用响应，
  // 该探测本身不构成账号枚举；passkeyAvailable=false 时不显示入口）。
  useEffect(() => {
    const trimmed = username.trim()
    if (!trimmed || !webauthnSupported() || totpPendingToken !== null) {
      setPasskeyAvailable(false)
      return
    }
    if (passkeyProbeTimer.current) clearTimeout(passkeyProbeTimer.current)
    passkeyProbeTimer.current = setTimeout(async () => {
      try {
        const options = await beginPasskeyLogin(trimmed)
        setPasskeyAvailable(options.passkeyAvailable)
      } catch {
        setPasskeyAvailable(false)
      }
    }, 350)
    return () => {
      if (passkeyProbeTimer.current) clearTimeout(passkeyProbeTimer.current)
    }
  }, [username, totpPendingToken])

  /** 登录成功共同路径：服务端核实身份 → 清上一账号足迹 → 翻门。
   * F015：带合法 ?next=（同源路径）时回到认证前目标，否则进应用首页。 */
  async function finishLogin() {
    let identity = null
    try {
      identity = identityFromSession(await getAuthSession())
    } catch {
      identity = null
    }
    resetAccountState(queryClient)
    useAuthStore.getState().setIdentity(identity)
    const next = readAuthRedirectTarget()
    if (next !== null && isSafeAuthRedirectPath(next)) {
      navigateToPath(next, true)
    } else if (readAppRoute() !== 'app') {
      navigateAppRoute('app', true)
    }
    setPassword('')
    setTotpCode('')
    setTotpPendingToken(null)
    setStatus('authenticated')
  }

  async function handlePasskeyLogin() {
    if (pending) return
    const trimmed = username.trim()
    if (!trimmed) return
    setPending(true)
    setFeedback({ kind: 'none' })
    try {
      const options = await beginPasskeyLogin(trimmed)
      const credential = (await navigator.credentials.get({
        publicKey: decodeRequestOptions(options.publicKey),
      })) as PublicKeyCredential | null
      if (!credential) {
        setFeedback({ kind: 'error', message: PASSKEY_FAILED_TEXT })
        return
      }
      const status = await finishPasskeyLogin({
        username: trimmed,
        challenge: options.challenge,
        credential: encodeAssertionResponse(credential),
      })
      if (status.authenticated) await finishLogin()
    } catch (error) {
      if (error instanceof ApiError && error.type === 'network_error') {
        setFeedback({ kind: 'offline', message: '网络不可用 —— 请检查网络连接后重试。' })
      } else if (error instanceof ApiError && error.type === 'rate_limited') {
        setFeedback({ kind: 'error', message: rateLimitedText(error.retryAfterSeconds) })
      } else if (error instanceof ApiError) {
        setFeedback({ kind: 'error', message: error.message })
      } else {
        // NotAllowedError 等：用户取消或设备拒绝。
        setFeedback({ kind: 'error', message: PASSKEY_FAILED_TEXT })
      }
    } finally {
      setPending(false)
    }
  }

  async function handleTotpSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (pending || totpPendingToken === null || totpCode.trim().length === 0) return
    setPending(true)
    setFeedback({ kind: 'none' })
    try {
      const status = await verifyTotpLogin(totpPendingToken, totpCode.trim())
      if (status.authenticated) {
        await finishLogin()
        return
      }
      setFeedback({ kind: 'error', message: TOTP_INVALID_TEXT })
    } catch (error) {
      if (error instanceof ApiError && error.type === 'network_error') {
        setFeedback({ kind: 'offline', message: '网络不可用 —— 请检查网络连接后重试。' })
      } else if (error instanceof ApiError && error.type === 'rate_limited') {
        setFeedback({ kind: 'error', message: rateLimitedText(error.retryAfterSeconds) })
      } else if (error instanceof ApiError && error.type === 'pending_token_invalid') {
        // pending token 过期/已用：回到密码步重新开始。
        setTotpPendingToken(null)
        setTotpCode('')
        setFeedback({ kind: 'error', message: '登录请求已过期，请重新登录。' })
      } else if (error instanceof ApiError && error.type === 'totp_code_invalid') {
        setFeedback({ kind: 'error', message: TOTP_INVALID_TEXT })
      } else if (error instanceof ApiError) {
        setFeedback({ kind: 'error', message: error.message })
      } else {
        setFeedback({ kind: 'error', message: TOTP_INVALID_TEXT })
      }
    } finally {
      setPending(false)
    }
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (pending || password.length === 0 || username.trim().length === 0) return
    setPending(true)
    setFeedback({ kind: 'none' })
    try {
      const response = await loginAccount(username.trim(), password)
      if (isTotpChallenge(response)) {
        // N007：密码正确 + 两步验证开启 → 第二步收集验证码。
        setTotpPendingToken(response.pendingToken)
        setPassword('')
        setTotpCode('')
        setTotpUseRecovery(false)
        return
      }
      if (response.authenticated) {
        await finishLogin()
      }
    } catch (error) {
      if (error instanceof ApiError && error.type === 'network_error') {
        setFeedback({
          kind: 'offline',
          message: '网络不可用 —— 请检查网络连接后重试。',
        })
      } else if (error instanceof ApiError && error.type === 'account_deactivated') {
        // N190：凭密码正确的停用账户 → 诚实状态页（非通用 401）。
        setFeedback({
          kind: 'deactivated',
          message: error.message,
          scheduledDeletionAt:
            error.extra !== null ? (error.extra.scheduledDeletionAt ?? null) : null,
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
              {totpPendingToken !== null ? '输入两步验证码' : '流光阅源 · 登录继续'}
            </p>
          </div>
        </div>

        {totpPendingToken === null ? (
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
                  className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 pr-11 text-base text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:border-[var(--lumi-text-tertiary)] focus-visible outline-2 -outline-offset-2 outline-[var(--lumi-focus-ring)] disabled:opacity-50"
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
              <div
                id="login-feedback"
                role="alert"
                aria-live="polite"
                data-testid={
                  feedback.kind === 'deactivated' ? 'login-deactivated' : undefined
                }
                className={
                  feedback.kind === 'offline'
                    ? 'text-xs leading-relaxed text-[var(--lumi-text-secondary)]'
                    : feedback.kind === 'deactivated'
                      ? 'rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3 text-xs leading-relaxed text-[var(--lumi-text-secondary)]'
                      : 'text-xs leading-relaxed text-[var(--lumi-danger)]'
                }
              >
                {feedback.kind === 'deactivated' ? (
                  <>
                    <p className="font-medium text-[var(--lumi-text-primary)]">账户已停用</p>
                    <p className="mt-1">{feedback.message}</p>
                    <p className="mt-1">恢复请联系运营者（宽限期内管理台「恢复」即撤销停用）；数据迁出见登录页下方说明。</p>
                  </>
                ) : (
                  feedback.message
                )}
              </div>
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

            {passkeyAvailable && (
              <Button
                type="button"
                variant="secondary"
                size="md"
                onClick={handlePasskeyLogin}
                disabled={pending || username.trim().length === 0}
                className="min-h-11 w-full"
                data-lumi-passkey-login=""
              >
                <Fingerprint aria-hidden className="size-4" />
                {pending ? '验证中…' : '使用通行密钥'}
              </Button>
            )}

            <p className="mt-1 text-center text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
              登录后在此设备保持登录，无需反复输入密码。
            </p>

            <div className="mt-1 flex flex-col items-center gap-1.5">
              <button
                type="button"
                onClick={() => {
                  // 去注册页时把合法 ?next= 带上（F020：注册成功后仍回认证前目标）。
                  const next = readAuthRedirectTarget()
                  if (next !== null) navigateToPath(`/register?next=${encodeURIComponent(next)}`)
                  else navigateAppRoute('register')
                }}
                data-testid="login-register-link"
                className="flex min-h-11 items-center gap-1.5 text-sm font-medium text-[var(--lumi-accent-text)] underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
              >
                <UserPlus aria-hidden className="size-4" />
                没有账号？注册新账号
              </button>
              <button
                type="button"
                onClick={() => navigateAppRoute('activate')}
                className="min-h-11 text-xs text-[var(--lumi-text-tertiary)] underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
              >
                有邀请链接？前往激活
              </button>
            </div>
          </form>
        ) : (
          <form onSubmit={handleTotpSubmit} className="flex flex-col gap-3" noValidate data-lumi-totp-step="">
            <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
              {totpUseRecovery
                ? '输入一个未使用过的恢复码。'
                : '输入认证器 App 当前生成的 6 位验证码。'}
            </p>
            <div>
              <label
                htmlFor="login-totp-code"
                className="mb-1.5 block text-sm font-medium text-[var(--lumi-text-primary)]"
              >
                {totpUseRecovery ? '恢复码' : '验证码'}
              </label>
              <input
                id="login-totp-code"
                type="text"
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value)}
                autoComplete="one-time-code"
                enterKeyHint="go"
                maxLength={totpUseRecovery ? 64 : 6}
                inputMode={totpUseRecovery ? 'text' : 'numeric'}
                disabled={pending}
                autoFocus
                aria-invalid={feedback.kind !== 'none' || undefined}
                aria-describedby={feedback.kind !== 'none' ? 'login-feedback' : undefined}
                className={
                  'min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-base text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:border-[var(--lumi-text-tertiary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)] disabled:opacity-50 ' +
                  (totpUseRecovery ? '' : 'font-mono tracking-widest')
                }
              />
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
              disabled={pending || totpCode.trim().length === 0}
              className="min-h-11 w-full"
              data-lumi-totp-submit=""
            >
              <LogIn aria-hidden className="size-4" />
              {pending ? '验证中…' : '验证并登录'}
            </Button>

            <button
              type="button"
              onClick={() => {
                setTotpUseRecovery((v) => !v)
                setTotpCode('')
              }}
              className="text-center text-xs text-[var(--lumi-text-secondary)] underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
            >
              {totpUseRecovery ? '改用验证器验证码' : '无法获取验证码？使用恢复码'}
            </button>

            <button
              type="button"
              onClick={() => {
                setTotpPendingToken(null)
                setTotpCode('')
                setFeedback({ kind: 'none' })
              }}
              className="text-center text-xs text-[var(--lumi-text-tertiary)] underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
            >
              返回重新登录
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
