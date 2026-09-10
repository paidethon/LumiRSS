/** AccountSecuritySection — 设置 → 账户与服务：会话账户安全。
 *
 * 仅在 LUMIRSS_AUTH_MODE=session 时渲染真实内容（basic 模式认证由
 * 代理层负责，这里不展示误导性的表单）。功能：
 * - 修改密码（当前 + 新 + 确认；成功后其他设备全部下线，本设备
 *   自动换发新 session，不打断当前操作）；
 * - 退出登录（本设备）/ 所有设备退出。
 * 密码只经 POST body 一次性传输，不进 localStorage / 状态持久化。
 */

import { useState } from 'react'
import { KeyRound, LogOut, MonitorSmartphone } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { ApiError, changePassword, logoutCurrent, logoutEverywhere } from '../../api/client'
import { useAuthStore } from '../../store/auth'
import { Button } from '../ui/Button'

const MIN_PASSWORD = 8

type Feedback = { kind: 'none' } | { kind: 'ok'; message: string } | { kind: 'error'; message: string }

function Field({
  id,
  label,
  ...rest
}: {
  id: string
  label: string
} & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div>
      <label
        htmlFor={id}
        className="mb-1.5 block text-sm font-medium text-[var(--lumi-text-primary)]"
      >
        {label}
      </label>
      <input
        id={id}
        type="password"
        autoComplete="new-password"
        className="min-h-10 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-sm text-[var(--lumi-text-primary)] transition-colors duration-[var(--lumi-motion-fast)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)] disabled:opacity-50"
        {...rest}
      />
    </div>
  )
}

export function AccountSecuritySection() {
  const mode = useAuthStore((s) => s.mode)
  const setStatus = useAuthStore((s) => s.setStatus)
  const queryClient = useQueryClient()

  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [pendingChange, setPendingChange] = useState(false)
  const [pendingLogout, setPendingLogout] = useState<'none' | 'current' | 'all'>('none')
  const [feedback, setFeedback] = useState<Feedback>({ kind: 'none' })

  if (mode !== 'session') return null

  async function handleChangePassword(event: React.FormEvent) {
    event.preventDefault()
    if (pendingChange) return
    if (next.length < MIN_PASSWORD) {
      setFeedback({ kind: 'error', message: `新密码至少 ${MIN_PASSWORD} 个字符。` })
      return
    }
    if (next !== confirm) {
      setFeedback({ kind: 'error', message: '两次输入的新密码不一致。' })
      return
    }
    setPendingChange(true)
    setFeedback({ kind: 'none' })
    try {
      await changePassword(current, next)
      setCurrent('')
      setNext('')
      setConfirm('')
      setFeedback({
        kind: 'ok',
        message: '密码已更新；其他设备已全部退出，本设备保持登录。',
      })
    } catch (error) {
      setFeedback({
        kind: 'error',
        message: error instanceof ApiError ? error.message : '修改失败，请稍后重试。',
      })
    } finally {
      setPendingChange(false)
    }
  }

  async function handleLogout(scope: 'current' | 'all') {
    if (pendingLogout !== 'none') return
    setPendingLogout(scope)
    try {
      // 先清本地缓存再请求：无论网络结果如何，本机不再保留已登出
      // 会话的文章数据（隐私优先；失败也只是多一次 401）。
      await queryClient.cancelQueries()
      queryClient.clear()
      if (scope === 'all') {
        await logoutEverywhere()
      } else {
        await logoutCurrent()
      }
    } catch {
      // 登出请求失败（如已离线）也切换到登录页 —— Cookie 可能仍在，
      // 下次联网后重登即可；不把用户困在已清空数据的界面里。
    } finally {
      setStatus('unauthenticated')
      setPendingLogout('none')
    }
  }

  return (
    <section className="py-2">
      <div className="flex items-center gap-2">
        <KeyRound aria-hidden className="size-4 text-[var(--lumi-text-tertiary)]" />
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">账户与安全</h3>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        修改密码后所有设备需要重新登录（本设备除外）。密码只以加密传输发送，
        不会保存在浏览器中。
      </p>

      <form onSubmit={handleChangePassword} className="mt-3 flex flex-col gap-3" noValidate>
        <Field
          id="account-current-password"
          label="当前密码"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          disabled={pendingChange}
          required
        />
        <Field
          id="account-new-password"
          label="新密码"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          disabled={pendingChange}
          minLength={MIN_PASSWORD}
          required
        />
        <Field
          id="account-confirm-password"
          label="确认新密码"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          disabled={pendingChange}
          required
        />
        {feedback.kind !== 'none' && (
          <p
            role="alert"
            aria-live="polite"
            className={
              feedback.kind === 'ok'
                ? 'text-xs leading-relaxed text-[var(--lumi-accent-text)]'
                : 'text-xs leading-relaxed text-[var(--lumi-danger)]'
            }
          >
            {feedback.message}
          </p>
        )}
        <div>
          <Button type="submit" variant="primary" size="sm" disabled={pendingChange || current.length === 0 || next.length === 0}>
            {pendingChange ? '更新中…' : '更新密码'}
          </Button>
        </div>
      </form>

      <div className="mt-6 border-t border-[var(--lumi-separator)] pt-4">
        <div className="flex items-center gap-2">
          <LogOut aria-hidden className="size-4 text-[var(--lumi-text-tertiary)]" />
          <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">登录会话</h3>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => handleLogout('current')}
            disabled={pendingLogout !== 'none'}
          >
            <LogOut aria-hidden className="size-4" />
            退出登录
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => handleLogout('all')}
            disabled={pendingLogout !== 'none'}
          >
            <MonitorSmartphone aria-hidden className="size-4" />
            所有设备退出
          </Button>
        </div>
      </div>
    </section>
  )
}
