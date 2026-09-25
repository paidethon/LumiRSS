/** AccountMenu — 侧栏底部的当前账号区块（0067 多账户，session 模式）。
 *
 * - 身份展示：username + 角色徽标（owner=运营者 / admin=管理员 /
 *   member=成员）。徽标只是入口可见性；后端才是权限真源。
 * - 菜单：修改密码（/auth/password）· 退出登录（/auth/logout）·
 *   退出所有设备（/auth/logout-all，需确认）。
 * - owner/admin 额外有「管理台」入口（/admin 路由；member 访问由
 *   管理台自身渲染 403 页）。
 * - basic 模式（mode!=='session' 或无身份）→ 零渲染：现状兼容，
 *   不显示身份与退出（AGENTS：Web 不建第二套 basic 登录 UI）。
 *
 * O157：登出成功统一走 resetAccountState——缓存与本地足迹清空后才
 * 翻认证门，A 的数据绝不残留给下一个登录者。
 */

import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { KeyRound, ListChecks, LogOut, MonitorSmartphone, Settings2 } from 'lucide-react'
import { ApiError, changePassword, logoutCurrent, logoutEverywhere } from '../api/client'
import { useAuthStore, type AuthIdentity } from '../store/auth'
import { resetAccountState } from '../lib/auth-reset'
import { navigateAppRoute } from '../lib/app-route'
import { Menu } from './ui/Menu'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { SessionRecapDialog } from './SessionRecapDialog'

const ROLE_LABELS: Record<AuthIdentity['role'], string> = {
  owner: '运营者',
  admin: '管理员',
  member: '成员',
}

/** 角色徽标颜色（语义 token，非硬编码色）。 */
const ROLE_BADGE_CLASSES: Record<AuthIdentity['role'], string> = {
  owner: 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]',
  admin: 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-secondary)]',
  member: 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-tertiary)]',
}

export default function AccountMenu() {
  const queryClient = useQueryClient()
  const mode = useAuthStore((s) => s.mode)
  const identity = useAuthStore((s) => s.identity)
  const setStatus = useAuthStore((s) => s.setStatus)
  const [passwordDialogOpen, setPasswordDialogOpen] = useState(false)
  const [logoutAllDialogOpen, setLogoutAllDialogOpen] = useState(false)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [passwordPending, setPasswordPending] = useState(false)
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [passwordDone, setPasswordDone] = useState(false)
  const [logoutPending, setLogoutPending] = useState(false)
  // N080：阅读成果（会话内实际创建的批注/问题/卡片汇总）。
  const [recapOpen, setRecapOpen] = useState(false)

  // basic 模式 / 身份未核实（登录响应探测失败的兜底）：不渲染身份与退出。
  if (mode !== 'session' || identity === null) return null

  /** 登出统一出口：服务端撤销 → 清本地 → 翻门。 */
  async function performLogout(kind: 'current' | 'all') {
    setLogoutPending(true)
    try {
      if (kind === 'all') await logoutEverywhere()
      else await logoutCurrent()
    } catch {
      // 服务端撤销失败（网络断）：Cookie 仍随后续请求携带，但不阻塞
      // 本地清理——用户明确要退出，绝不把人困在已不可信的界面里。
    }
    resetAccountState(queryClient)
    useAuthStore.getState().setIdentity(null)
    setLogoutPending(false)
    setStatus('unauthenticated')
  }

  async function handleChangePassword(event?: React.FormEvent) {
    event?.preventDefault()
    if (passwordPending || newPassword.length < 8) return
    setPasswordPending(true)
    setPasswordError(null)
    try {
      await changePassword(currentPassword, newPassword)
      setPasswordDone(true)
      setCurrentPassword('')
      setNewPassword('')
    } catch (error) {
      if (error instanceof ApiError && error.type === 'invalid_credentials') {
        setPasswordError('当前密码不正确。')
      } else if (error instanceof ApiError && error.type === 'weak_password') {
        setPasswordError(error.message)
      } else if (error instanceof ApiError && error.type === 'network_error') {
        setPasswordError('网络不可用 —— 请检查网络连接后重试。')
      } else {
        setPasswordError('修改失败，请稍后重试。')
      }
    } finally {
      setPasswordPending(false)
    }
  }

  return (
    <div
      className="mt-2 flex shrink-0 items-center gap-1 border-t border-[var(--lumi-separator)] px-3 pb-1 pt-2"
      data-testid="account-menu"
    >
      <Menu
        trigger={({ triggerProps }) => (
          <button
            type="button"
            {...triggerProps}
            data-testid="account-menu-trigger"
            className="flex min-h-11 min-w-0 flex-1 items-center gap-2 rounded-[var(--lumi-radius-md)] px-2 text-left transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            <span className="flex size-7 shrink-0 items-center justify-center rounded-[var(--lumi-radius-full)] bg-[var(--lumi-accent-soft)] text-xs font-semibold text-[var(--lumi-accent-text)]" aria-hidden>
              {identity.username.slice(0, 1).toUpperCase()}
            </span>
            <span className="flex min-w-0 flex-col">
              <span className="truncate text-sm font-medium text-[var(--lumi-text-primary)]" data-testid="account-username">
                {identity.username}
              </span>
              <span
                className={`mt-0.5 w-fit rounded-[var(--lumi-radius-full)] px-1.5 py-px text-[11px] leading-4 ${ROLE_BADGE_CLASSES[identity.role]}`}
                data-testid="account-role-badge"
              >
                {ROLE_LABELS[identity.role]}
              </span>
            </span>
          </button>
        )}
        items={[
          { key: 'recap', content: <><ListChecks aria-hidden className="size-4" />阅读成果</> },
          { key: 'password', content: <><KeyRound aria-hidden className="size-4" />修改密码</> },
          ...(identity.role === 'owner' || identity.role === 'admin'
            ? [{ key: 'admin', content: <><Settings2 aria-hidden className="size-4" />管理台</> }]
            : []),
          { key: 'logout', content: <><LogOut aria-hidden className="size-4" />退出登录</> },
          { key: 'logout-all', content: <><MonitorSmartphone aria-hidden className="size-4" />退出所有设备</> },
        ]}
        onSelect={(key) => {
          if (key === 'recap') {
            setRecapOpen(true)
          } else if (key === 'password') {
            setPasswordDone(false)
            setPasswordError(null)
            setPasswordDialogOpen(true)
          } else if (key === 'admin') {
            navigateAppRoute('admin')
          } else if (key === 'logout') {
            void performLogout('current')
          } else if (key === 'logout-all') {
            setLogoutAllDialogOpen(true)
          }
        }}
      />

      {/* N080：阅读成果（tools 入口；device-local 统计 + 会话笔记） */}
      <SessionRecapDialog open={recapOpen} onClose={() => setRecapOpen(false)} />

      {/* 修改密码（成功后全部会话已轮换，本设备自动换发新 session） */}
      <Dialog
        open={passwordDialogOpen}
        onClose={() => setPasswordDialogOpen(false)}
        title="修改密码"
        footer={
          <>
            <Button variant="ghost" onClick={() => setPasswordDialogOpen(false)}>
              关闭
            </Button>
            <Button
              variant="primary"
              onClick={() => void handleChangePassword()}
              disabled={passwordPending || newPassword.length < 8 || currentPassword.length === 0}
            >
              {passwordPending ? '提交中…' : '修改密码'}
            </Button>
          </>
        }
      >
        {passwordDone ? (
          <p role="status" className="text-sm text-[var(--lumi-text-primary)]">
            密码已修改。其它设备已被退出，本设备保持登录。
          </p>
        ) : (
          <form id="change-password-form" onSubmit={handleChangePassword} className="flex flex-col gap-3" noValidate>
            <div>
              <label htmlFor="change-current-password" className="mb-1.5 block text-sm font-medium text-[var(--lumi-text-primary)]">
                当前密码
              </label>
              <input
                id="change-current-password"
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                autoComplete="current-password"
                disabled={passwordPending}
                className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-base text-[var(--lumi-text-primary)] transition-colors duration-[var(--lumi-motion-fast)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)] disabled:opacity-50"
              />
            </div>
            <div>
              <label htmlFor="change-new-password" className="mb-1.5 block text-sm font-medium text-[var(--lumi-text-primary)]">
                新密码
              </label>
              <input
                id="change-new-password"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                autoComplete="new-password"
                disabled={passwordPending}
                aria-invalid={passwordError !== null || undefined}
                aria-describedby={passwordError !== null ? 'change-password-error' : undefined}
                className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-base text-[var(--lumi-text-primary)] transition-colors duration-[var(--lumi-motion-fast)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)] disabled:opacity-50"
              />
              {passwordError !== null && (
                <p id="change-password-error" role="alert" className="mt-1 text-xs leading-relaxed text-[var(--lumi-danger)]">
                  {passwordError}
                </p>
              )}
            </div>
          </form>
        )}
      </Dialog>

      {/* 退出所有设备：破坏性确认（撤销本用户全部 session，含本机） */}
      <Dialog
        open={logoutAllDialogOpen}
        onClose={() => setLogoutAllDialogOpen(false)}
        title="退出所有设备"
        footer={
          <>
            <Button variant="ghost" onClick={() => setLogoutAllDialogOpen(false)}>
              取消
            </Button>
            <Button
              variant="danger"
              disabled={logoutPending}
              onClick={() => {
                setLogoutAllDialogOpen(false)
                void performLogout('all')
              }}
            >
              退出所有设备
            </Button>
          </>
        }
      >
        <p className="text-sm leading-relaxed text-[var(--lumi-text-primary)]">
          将撤销你在所有设备上的登录会话（包括本机），需要重新登录才能继续使用。
        </p>
      </Dialog>
    </div>
  )
}
