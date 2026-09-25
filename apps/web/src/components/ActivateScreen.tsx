/** ActivateScreen — 邀请激活页（/activate?token=…，未登录可达）。
 *
 * 四态（0067 + N002）：
 * 1. 无效/过期邀请 → 诚实单一提示，不含原因细节（不泄露邀请是
 *    「不存在/已过期/已撤销/已使用」中的哪种）；
 * 2. 等待生效（预约生效邀请，N002）→ 诚实显示服务器给出的生效时间
 *    与服务器当前时间——服务器时钟是唯一时钟，本机墙钟只用于显示；
 * 3. 正常表单 → 用户名 + 密码 + 确认 + 可选显示名；客户端预校验
 *    username 规则与密码长度（服务端仍权威校验）；
 * 4. 成功 → 服务端已自动登录（会话 Cookie），进入应用。
 *
 * 独立 FreshRSS 绑定状态：freshrssReady=false 不是错误——显示
 * 「RSS 源绑定待运营者准备，稍后自动完成」说明文案；永不回退到
 * 共享凭据（架构不变量）。
 */

import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Clock, Eye, EyeOff, RefreshCw } from 'lucide-react'
import {
  ApiError,
  activateWithInvite,
  getActivationPreview,
  getAuthSession,
  type ActivationPreview,
} from '../api/client'
import { identityFromSession, useAuthStore } from '../store/auth'
import { resetAccountState } from '../lib/auth-reset'
import { navigateAppRoute, readActivateToken } from '../lib/app-route'
import { passwordStrength } from '../lib/password-strength'
import { Button } from './ui/Button'
import { PasswordStrengthMeter } from './ui/PasswordStrengthMeter'

/** 与 BFF USERNAME_RE 同规则：3–32 位，小写字母/数字/`-`/`_`，字母或数字开头。 */
const USERNAME_PATTERN = /^[a-z0-9][a-z0-9_-]{2,31}$/
const MIN_PASSWORD_LENGTH = 8

const INVALID_INVITE_TEXT = '邀请链接无效或已过期，请联系运营者重新获取。'

type Phase =
  | { kind: 'loading' }
  | { kind: 'invalid' }
  | { kind: 'network'; detail: string }
  | { kind: 'waiting'; notBefore: string; serverTime: string | null }
  | { kind: 'form'; freshrssReady: boolean }
  | { kind: 'submitting' }

function usernameIssue(value: string): string | null {
  if (value === '') return '请输入用户名。'
  if (!USERNAME_PATTERN.test(value)) {
    return '用户名需 3–32 位，仅限小写字母、数字、- 或 _，并以字母或数字开头。'
  }
  return null
}

/** 服务器给出的 ISO 时刻 → 本地显示（只影响显示，不参与任何判断）。 */
function formatServerInstant(value: string): string {
  const parsed = Date.parse(value)
  if (Number.isNaN(parsed)) return value
  return new Date(parsed).toLocaleString('zh-CN', { hour12: false })
}

function passwordIssue(value: string): string | null {
  if (value === '') return '请输入密码。'
  if (value.length < MIN_PASSWORD_LENGTH) {
    return `密码至少 ${MIN_PASSWORD_LENGTH} 位。`
  }
  return null
}

export default function ActivateScreen() {
  const queryClient = useQueryClient()
  // token 只读一次（激活链接是一次性 URL；重试按钮用 reloadKey 重跑预览）
  const [token] = useState<string | null>(() => readActivateToken())
  const [reloadKey, setReloadKey] = useState(0)
  const [phase, setPhase] = useState<Phase>(() =>
    token === null ? { kind: 'invalid' } : { kind: 'loading' },
  )
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [reveal, setReveal] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<{ username?: string; password?: string; confirm?: string }>({})
  const [formError, setFormError] = useState<string | null>(null)

  // 预览加载：只挂载/重试时跑一次；setState 全部在 await 之后（非同步
  // effect 写），cancelled 守卫防重试竞态。
  useEffect(() => {
    if (token === null) return
    let cancelled = false
    void (async () => {
      try {
        const preview: ActivationPreview = await getActivationPreview(token)
        if (cancelled) return
        if (!preview.valid && preview.notBefore) {
          // 预约生效（N002）：以服务器给出的时间为准，诚实等待。
          setPhase({ kind: 'waiting', notBefore: preview.notBefore, serverTime: preview.serverTime ?? null })
        } else if (!preview.valid) {
          // 诚实单一提示：无效/过期/已用/已撤销不区分。
          setPhase({ kind: 'invalid' })
        } else {
          setPhase({ kind: 'form', freshrssReady: preview.freshrssReady })
        }
      } catch (error) {
        if (cancelled) return
        setPhase({
          kind: 'network',
          detail:
            error instanceof ApiError && error.type !== 'network_error'
              ? error.message
              : '网络不可用 —— 请检查网络连接后重试。',
        })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token, reloadKey])

  function retryPreview(): void {
    setPhase(token === null ? { kind: 'invalid' } : { kind: 'loading' })
    setReloadKey((k) => k + 1)
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (phase.kind !== 'form' || token === null) return
    const issues: typeof fieldErrors = {}
    const usernameError = usernameIssue(username)
    if (usernameError !== null) issues.username = usernameError
    const passwordError = passwordIssue(password)
    if (passwordError !== null) issues.password = passwordError
    if (confirm !== password) issues.confirm = '两次输入的密码不一致。'
    setFieldErrors(issues)
    setFormError(null)
    if (Object.keys(issues).length > 0) return

    setPhase({ kind: 'submitting' })
    try {
      const status = await activateWithInvite({
        token,
        username,
        password,
        displayName: displayName !== '' ? displayName : null,
      })
      if (status.authenticated) {
        // 身份由服务端核实；O157：激活即换号入口，先清缓存再进门。
        let identity = null
        try {
          identity = identityFromSession(await getAuthSession())
        } catch {
          identity = null
        }
        resetAccountState(queryClient)
        useAuthStore.getState().setIdentity(identity)
        navigateAppRoute('app', true)
        useAuthStore.getState().setStatus('authenticated')
      } else {
        setPhase({ kind: 'form', freshrssReady: false })
        setFormError('激活未完成，请稍后重试。')
      }
    } catch (error) {
      if (error instanceof ApiError && error.type === 'invite_invalid') {
        setPhase({ kind: 'invalid' })
      } else if (error instanceof ApiError && error.type === 'invite_not_active') {
        // 提前提交（竞态或预览过期）：落到等待态，以服务器时间为准。
        setPhase({
          kind: 'waiting',
          notBefore: error.extra?.notBefore ?? '',
          serverTime: error.extra?.serverTime ?? null,
        })
      } else if (error instanceof ApiError && (error.type === 'invalid_username' || error.type === 'weak_password')) {
        setPhase({ kind: 'form', freshrssReady: false })
        setFormError(error.message)
      } else if (error instanceof ApiError && error.type === 'network_error') {
        setPhase({ kind: 'form', freshrssReady: false })
        setFormError('网络不可用 —— 请检查网络连接后重试。')
      } else {
        setPhase({ kind: 'form', freshrssReady: false })
        setFormError('激活失败，请稍后重试。')
      }
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-[var(--lumi-canvas)] px-6 py-[max(1.5rem,env(safe-area-inset-top))] pb-[max(1.5rem,env(safe-area-inset-bottom))]">
      <div className="w-full max-w-sm" data-testid="activate-screen">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <img src="/icons/lumirss-icon.svg" alt="" className="size-14" decoding="async" />
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-[var(--lumi-text-primary)]">
              激活账号
            </h1>
            <p className="mt-1 text-sm text-[var(--lumi-text-secondary)]">
              流光阅源 · 邀请制加入
            </p>
          </div>
        </div>

        {phase.kind === 'loading' && (
          <p role="status" className="text-center text-sm text-[var(--lumi-text-secondary)]">
            正在验证邀请链接…
          </p>
        )}

        {phase.kind === 'invalid' && (
          <div className="flex flex-col items-center gap-4 text-center">
            <p role="alert" className="text-sm leading-relaxed text-[var(--lumi-text-primary)]">
              {INVALID_INVITE_TEXT}
            </p>
            <Button
              variant="secondary"
              onClick={() => {
                retryPreview()
              }}
            >
              重新检查
            </Button>
          </div>
        )}

        {phase.kind === 'waiting' && (
          <div
            className="flex flex-col items-center gap-4 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-4 text-center"
            data-testid="invite-waiting"
          >
            <Clock aria-hidden className="size-6 text-[var(--lumi-text-tertiary)]" />
            <p role="status" className="text-sm font-medium text-[var(--lumi-text-primary)]">
              邀请尚未生效，请等待生效后再激活。
            </p>
            <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
              {phase.notBefore !== '' && (
                <>
                  生效时间：
                  <time dateTime={phase.notBefore}>{formatServerInstant(phase.notBefore)}</time>
                  <br />
                </>
              )}
              {phase.serverTime !== null && (
                <>
                  服务器当前时间：
                  <time dateTime={phase.serverTime}>{formatServerInstant(phase.serverTime)}</time>
                </>
              )}
            </p>
            <Button variant="secondary" onClick={retryPreview}>
              重新检查
            </Button>
          </div>
        )}

        {phase.kind === 'network' && (
          <div className="flex flex-col items-center gap-4 text-center">
            <p role="alert" className="text-sm leading-relaxed text-[var(--lumi-text-secondary)]">
              {phase.detail}
            </p>
            <Button
              variant="secondary"
              onClick={() => {
                retryPreview()
              }}
            >
              重试
            </Button>
          </div>
        )}

        {(phase.kind === 'form' || phase.kind === 'submitting') && (
          <form onSubmit={handleSubmit} className="flex flex-col gap-3" noValidate>
            {phase.kind === 'form' && !phase.freshrssReady && (
              <p
                role="note"
                data-testid="binding-pending-note"
                className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]"
              >
                RSS 源绑定待运营者准备，稍后自动完成——账号本身可正常使用。
              </p>
            )}

            <div>
              <label
                htmlFor="activate-username"
                className="mb-1.5 block text-sm font-medium text-[var(--lumi-text-primary)]"
              >
                用户名
              </label>
              <input
                id="activate-username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value.toLowerCase())}
                autoComplete="username"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                inputMode="text"
                disabled={phase.kind === 'submitting'}
                aria-invalid={fieldErrors.username !== undefined || undefined}
                aria-describedby={fieldErrors.username !== undefined ? 'activate-username-error' : undefined}
                className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-base text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:border-[var(--lumi-text-tertiary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)] disabled:opacity-50"
                placeholder="小写字母、数字、- 或 _"
              />
              {fieldErrors.username !== undefined && (
                <p id="activate-username-error" className="mt-1 text-xs leading-relaxed text-[var(--lumi-danger)]">
                  {fieldErrors.username}
                </p>
              )}
            </div>

            <div>
              <label
                htmlFor="activate-display-name"
                className="mb-1.5 block text-sm font-medium text-[var(--lumi-text-primary)]"
              >
                显示名（可选）
              </label>
              <input
                id="activate-display-name"
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                autoComplete="nickname"
                maxLength={64}
                disabled={phase.kind === 'submitting'}
                className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-base text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:border-[var(--lumi-text-tertiary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)] disabled:opacity-50"
                placeholder="昵称或真名"
              />
            </div>

            <div>
              <label
                htmlFor="activate-password"
                className="mb-1.5 block text-sm font-medium text-[var(--lumi-text-primary)]"
              >
                密码
              </label>
              <div className="relative">
                <input
                  id="activate-password"
                  type={reveal ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password"
                  disabled={phase.kind === 'submitting'}
                  aria-invalid={fieldErrors.password !== undefined || undefined}
                  aria-describedby={fieldErrors.password !== undefined ? 'activate-password-error' : undefined}
                  className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 pr-11 text-base text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:border-[var(--lumi-text-tertiary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)] disabled:opacity-50"
                  placeholder="至少 8 位"
                />
                <button
                  type="button"
                  onClick={() => setReveal((v) => !v)}
                  aria-label={reveal ? '隐藏密码' : '显示密码'}
                  className="absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                >
                  {reveal ? <EyeOff aria-hidden className="size-4" /> : <Eye aria-hidden className="size-4" />}
                </button>
              </div>
              {fieldErrors.password !== undefined && (
                <p id="activate-password-error" className="mt-1 text-xs leading-relaxed text-[var(--lumi-danger)]">
                  {fieldErrors.password}
                </p>
              )}
              {/* N005：本地强度提示（纯函数；不发任何网络请求）。 */}
              <PasswordStrengthMeter
                strength={passwordStrength(password)}
                id="activate-password-strength"
              />
            </div>

            <div>
              <label
                htmlFor="activate-confirm"
                className="mb-1.5 block text-sm font-medium text-[var(--lumi-text-primary)]"
              >
                确认密码
              </label>
              <input
                id="activate-confirm"
                type={reveal ? 'text' : 'password'}
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
                disabled={phase.kind === 'submitting'}
                aria-invalid={fieldErrors.confirm !== undefined || undefined}
                aria-describedby={fieldErrors.confirm !== undefined ? 'activate-confirm-error' : undefined}
                className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-base text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:border-[var(--lumi-text-tertiary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)] disabled:opacity-50"
                placeholder="再输入一次"
              />
              {fieldErrors.confirm !== undefined && (
                <p id="activate-confirm-error" className="mt-1 text-xs leading-relaxed text-[var(--lumi-danger)]">
                  {fieldErrors.confirm}
                </p>
              )}
            </div>

            {formError !== null && (
              <p role="alert" className="text-xs leading-relaxed text-[var(--lumi-danger)]">
                {formError}
              </p>
            )}

            <Button
              type="submit"
              variant="primary"
              className="min-h-11 w-full"
              disabled={phase.kind === 'submitting'}
            >
              <RefreshCw aria-hidden className="size-4" />
              {phase.kind === 'submitting' ? '激活中…' : '激活并进入'}
            </Button>

            <p className="mt-1 text-center text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
              激活后你将拥有独立的 RSS 账号绑定，不与他人共用凭据。
            </p>
          </form>
        )}
      </div>
    </div>
  )
}
