/** AdminScreen — 管理台（/admin，owner/admin 可用）。
 *
 * 任务分组（非卡片墙）：成员列表 / 邀请管理 / FreshRSS 池 / 系统面板。
 * 桌面双栏（lg:grid-cols-2，池状态横跨右列）、系统面板横贯全宽、移动单栏。
 *
 * 系统面板（P11）：数据只来自 GET /admin/system（版本/运行时/内存、
 * 存储计数、服务健康、后台任务——服务端派生，绝无秘密值）与
 * GET /admin/audit（已脱敏审计尾部）；「我的订阅/条目/资料库」是当前
 * 管理员自己库的计数，管理台没有跨成员内容视图。刷新按钮同时重取
 * 两个查询；加载/错误/空态齐备，状态一律带文字标签。
 *
 * 权限语义：入口只对 owner/admin 渲染（本地身份徽标），member 访问
 * 与本地身份缺失时的 403 提示页都是「诚实转述后端 403」——后端才是
 * 权限真源；任何 mutation 的 403 都同样落到提示页文案。
 *
 * 危险操作（暂停成员 / 撤销会话 / 重置密码 / 撤销邀请）一律先过
 * 确认对话框（Base UI Dialog 拥有焦点陷阱/Escape/滚动锁）。
 * 重置密码与创建邀请的一次性链接（token 只出现一次）就地展示 +
 * 复制按钮，并诚实标注「只显示这一次」。
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Check, Copy, Layers, Plus, RefreshCw, Trash2 } from 'lucide-react'
import {
  ApiError,
  createAdminInvite,
  createInviteScheme,
  deleteInviteScheme,
  generateInvitesFromScheme,
  getAdminSystem,
  getFreshRssPool,
  getInviteFunnel,
  getRegistrationPolicy,
  listAdminAudit,
  listAdminInvites,
  listAdminUsers,
  listInviteSchemes,
  pauseAdminUser,
  registerFreshRssPool,
  resetAdminUserPassword,
  resumeAdminUser,
  revokeAdminInvite,
  revokeAdminUserSessions,
  updateRegistrationPolicy,
  type AdminInvite,
  type AdminInviteCreated,
  type AdminUser,
  type InviteScheme,
} from '../../api/client'
import { useAuthStore } from '../../store/auth'
import { navigateAppRoute } from '../../lib/app-route'
import { formatListTime, formatRelativeTime } from '../../lib/date-format'
import { Button } from '../ui/Button'
import { Dialog } from '../ui/Dialog'
import { Skeleton } from '../ui/Skeleton'
import { Switch } from '../ui/Switch'

const ROLE_LABELS: Record<AdminUser['role'], string> = {
  owner: '运营者',
  admin: '管理员',
  member: '成员',
}

/** 邀请的台账状态（服务端四态互斥，按「已用 > 已撤销 > 等待生效 > 已过期 > 有效」判）。
 * 等待生效的邀请仍可撤销（操作者必须能收回未开闸的邀请）。 */
function inviteState(invite: AdminInvite): { label: string; actionable: boolean } {
  if (invite.usedAt !== null) return { label: '已使用', actionable: false }
  if (invite.revokedAt !== null) return { label: '已撤销', actionable: false }
  if (invite.notBefore !== null && Date.parse(invite.notBefore) > Date.now()) {
    return { label: '等待生效', actionable: true }
  }
  if (invite.expiresAt !== null && Date.parse(invite.expiresAt) <= Date.now()) {
    return { label: '已过期', actionable: false }
  }
  return { label: '有效', actionable: true }
}

/** 稳定的 mutation 错误文案（后端 message 是英文技术细节，转述为诚实中文）。 */
function adminActionError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.type === 'network_error') return '网络不可用 —— 请检查网络连接后重试。'
    if (error.status === 403) return '需要管理员权限，操作被服务端拒绝。'
    if (error.message !== '') return error.message
  }
  return '操作失败，请稍后重试。'
}

/** 一次性链接展示 + 复制（token 只出现一次的诚实 UI）。 */
function OneTimeLink({ url }: { url: string }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }
  return (
    <div
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
      data-testid="one-time-link"
    >
      <p className="text-xs font-medium text-[var(--lumi-text-primary)]">
        一次性链接（只显示这一次，请立即复制并发给对方）：
      </p>
      <code className="break-all text-xs leading-relaxed text-[var(--lumi-text-secondary)]">{url}</code>
      <Button size="sm" variant="secondary" onClick={() => void copy()} className="self-start">
        {copied ? <Check aria-hidden className="size-4" /> : <Copy aria-hidden className="size-4" />}
        {copied ? '已复制' : '复制链接'}
      </Button>
    </div>
  )
}

/** 激活链接（同源 + /activate?token=…）。 */
function activationLink(token: string): string {
  return `${window.location.origin}/activate?token=${encodeURIComponent(token)}`
}

interface ConfirmState {
  title: string
  body: string
  confirmLabel: string
  action: () => Promise<void>
}

function SectionHeading({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="mb-3">
      <h2 className="text-sm font-semibold text-[var(--lumi-text-primary)]">{title}</h2>
      {hint !== undefined && (
        <p className="mt-0.5 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">{hint}</p>
      )}
    </div>
  )
}

const badgeBase = 'rounded-[var(--lumi-radius-full)] px-1.5 py-px text-[11px] leading-4'

// ===== 成员列表 ============================================================

function MembersSection({ onConfirm }: { onConfirm: (state: ConfirmState) => void }) {
  const queryClient = useQueryClient()
  const users = useQuery({
    queryKey: ['admin', 'users'],
    queryFn: ({ signal }) => listAdminUsers(signal),
    staleTime: 10_000,
  })
  const [actionError, setActionError] = useState<string | null>(null)
  const [resetLink, setResetLink] = useState<string | null>(null)

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['admin', 'users'] })

  const pause = useMutation({
    mutationFn: (userId: string) => pauseAdminUser(userId),
    onSuccess: () => void invalidate(),
    onError: (error) => setActionError(adminActionError(error)),
  })
  const resume = useMutation({
    mutationFn: (userId: string) => resumeAdminUser(userId),
    onSuccess: () => void invalidate(),
    onError: (error) => setActionError(adminActionError(error)),
  })
  const revokeSessions = useMutation({
    mutationFn: (userId: string) => revokeAdminUserSessions(userId),
    onSuccess: () => void invalidate(),
    onError: (error) => setActionError(adminActionError(error)),
  })
  const resetPassword = useMutation({
    mutationFn: (userId: string) => resetAdminUserPassword(userId),
    onSuccess: (result) => {
      setResetLink(activationLink(result.recoveryToken))
      void invalidate()
    },
    onError: (error) => setActionError(adminActionError(error)),
  })

  if (users.isPending) {
    return (
      <section aria-label="成员列表" aria-busy="true">
        <SectionHeading title="成员" hint="账号目录与生命周期" />
        <div className="flex flex-col gap-2">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      </section>
    )
  }
  if (users.isError) {
    return (
      <section aria-label="成员列表">
        <SectionHeading title="成员" hint="账号目录与生命周期" />
        <p role="alert" className="text-sm leading-relaxed text-[var(--lumi-danger)]">
          {adminActionError(users.error)}
        </p>
      </section>
    )
  }

  return (
    <section aria-label="成员列表">
      <SectionHeading title="成员" hint="账号目录与生命周期。暂停会同时撤销该成员的全部会话。" />
      <ul className="flex flex-col divide-y divide-[var(--lumi-separator)]" data-testid="admin-user-list">
        {users.data.map((user) => (
          <li key={user.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5">
            <div className="min-w-0 flex-1">
              <p className="flex flex-wrap items-center gap-1.5 text-sm font-medium text-[var(--lumi-text-primary)]">
                <span className="truncate">{user.username}</span>
                <span className={`${badgeBase} bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-tertiary)]`}>
                  {ROLE_LABELS[user.role]}
                </span>
                {user.status === 'paused' ? (
                  <span className={`${badgeBase} bg-[var(--lumi-danger)] text-[var(--lumi-danger-contrast)]`}>已暂停</span>
                ) : (
                  <span className={`${badgeBase} bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]`}>正常</span>
                )}
                {user.schemeName !== null && (
                  <span className={`${badgeBase} bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-tertiary)]`}>
                    方案 · {user.schemeName}
                  </span>
                )}
              </p>
              <p className="mt-0.5 truncate text-xs text-[var(--lumi-text-tertiary)]">
                {user.displayName ?? '未设置显示名'}
                {user.createdAt !== null ? ` · 加入于 ${formatListTime(user.createdAt, 'absolute')}` : ''}
              </p>
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-1.5">
              {user.status === 'active' ? (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={pause.isPending}
                  onClick={() =>
                    onConfirm({
                      title: `暂停 ${user.username}？`,
                      body: '暂停后该成员无法登录，其所有设备的会话将被撤销；恢复后可重新登录。',
                      confirmLabel: '暂停',
                      action: () => pause.mutateAsync(user.id),
                    })
                  }
                >
                  暂停
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={resume.isPending}
                  onClick={() => resume.mutate(user.id)}
                >
                  恢复
                </Button>
              )}
              <Button
                size="sm"
                variant="ghost"
                disabled={revokeSessions.isPending}
                onClick={() =>
                  onConfirm({
                    title: `撤销 ${user.username} 的全部会话？`,
                    body: '该成员在所有设备上将被强制下线（密码不变），可重新登录。',
                    confirmLabel: '撤销会话',
                    action: () => revokeSessions.mutateAsync(user.id),
                  })
                }
              >
                撤销会话
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={resetPassword.isPending}
                onClick={() =>
                  onConfirm({
                    title: `重置 ${user.username} 的密码？`,
                    body: '服务端会设置一个无人知晓的新密码并撤销其全部会话，随后生成一次性恢复链接，由你转交给该成员重设密码（不会发送邮件）。',
                    confirmLabel: '重置密码',
                    action: async () => {
                      await resetPassword.mutateAsync(user.id)
                    },
                  })
                }
              >
                重置密码
              </Button>
            </div>
          </li>
        ))}
      </ul>

      {actionError !== null && (
        <p role="alert" className="mt-2 text-xs leading-relaxed text-[var(--lumi-danger)]">
          {actionError}
        </p>
      )}

      {resetLink !== null && (
        <div className="mt-3">
          <OneTimeLink url={resetLink} />
        </div>
      )}
    </section>
  )
}

// ===== 邀请管理 ============================================================

function InvitesSection({ onConfirm }: { onConfirm: (state: ConfirmState) => void }) {
  const queryClient = useQueryClient()
  const invites = useQuery({
    queryKey: ['admin', 'invites'],
    queryFn: ({ signal }) => listAdminInvites(signal),
    staleTime: 10_000,
  })
  const [label, setLabel] = useState('')
  const [ttlHours, setTtlHours] = useState('72')
  const [created, setCreated] = useState<{ url: string; at: number } | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  const create = useMutation({
    mutationFn: () =>
      createAdminInvite({
        kind: 'signup',
        label: label !== '' ? label : null,
        ttlHours: ttlHours !== '' ? Number.parseInt(ttlHours, 10) : undefined,
      }),
    onSuccess: (result) => {
      setCreated({ url: activationLink(result.token), at: Date.now() })
      setLabel('')
      void queryClient.invalidateQueries({ queryKey: ['admin', 'invites'] })
      void queryClient.invalidateQueries({ queryKey: ['admin', 'funnel'] })
    },
    onError: (error) => setFormError(adminActionError(error)),
  })
  const revoke = useMutation({
    mutationFn: (inviteId: string) => revokeAdminInvite(inviteId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['admin', 'invites'] })
      void queryClient.invalidateQueries({ queryKey: ['admin', 'funnel'] })
    },
    onError: (error) => setFormError(adminActionError(error)),
  })

  return (
    <section aria-label="邀请管理">
      <SectionHeading title="邀请" hint="signup 邀请允许一名新成员自助激活；token 只在创建时出现一次。" />

      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          setFormError(null)
          create.mutate()
        }}
        data-testid="invite-create-form"
      >
        <div className="min-w-36 flex-1">
          <label htmlFor="invite-label" className="mb-1 block text-xs font-medium text-[var(--lumi-text-secondary)]">
            备注（可选）
          </label>
          <input
            id="invite-label"
            type="text"
            value={label}
            maxLength={64}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="如：给 alice 的邀请"
            className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-sm text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)]"
          />
        </div>
        <div className="w-24">
          <label htmlFor="invite-ttl" className="mb-1 block text-xs font-medium text-[var(--lumi-text-secondary)]">
            有效期（小时）
          </label>
          <input
            id="invite-ttl"
            type="number"
            min={1}
            max={720}
            value={ttlHours}
            onChange={(e) => setTtlHours(e.target.value)}
            className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-sm text-[var(--lumi-text-primary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)]"
          />
        </div>
        <Button type="submit" variant="primary" disabled={create.isPending} className="min-h-11">
          <Plus aria-hidden className="size-4" />
          {create.isPending ? '创建中…' : '创建邀请'}
        </Button>
      </form>

      {formError !== null && (
        <p role="alert" className="mt-2 text-xs leading-relaxed text-[var(--lumi-danger)]">
          {formError}
        </p>
      )}

      {created !== null && (
        <div className="mt-3">
          <OneTimeLink url={created.url} />
        </div>
      )}

      <div className="mt-3">
        {invites.isPending ? (
          <div aria-busy="true">
            <Skeleton className="h-8 w-full" />
          </div>
        ) : invites.isError ? (
          <p role="alert" className="text-sm text-[var(--lumi-danger)]">
            {adminActionError(invites.error)}
          </p>
        ) : invites.data.length === 0 ? (
          <p className="text-sm text-[var(--lumi-text-tertiary)]">还没有邀请记录。</p>
        ) : (
          <ul className="flex flex-col divide-y divide-[var(--lumi-separator)]" data-testid="admin-invite-list">
            {invites.data.map((invite) => {
              const state = inviteState(invite)
              return (
                <li key={invite.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
                  <div className="min-w-0 flex-1">
                    <p className="flex flex-wrap items-center gap-1.5 text-sm text-[var(--lumi-text-primary)]">
                      <span className="truncate">{invite.label ?? '未命名邀请'}</span>
                      <span className={`${badgeBase} bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-tertiary)]`}>
                        {invite.kind === 'recovery' ? '恢复' : '注册'}
                      </span>
                      {invite.schemeId !== null && (
                        <span className={`${badgeBase} bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]`}>方案</span>
                      )}
                      <span
                        className={`${badgeBase} ${
                          state.label === '有效'
                            ? 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]'
                            : 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-tertiary)]'
                        }`}
                      >
                        {state.label}
                      </span>
                    </p>
                    <p className="mt-0.5 text-xs text-[var(--lumi-text-tertiary)]">
                      {invite.createdAt !== null ? `创建于 ${formatListTime(invite.createdAt, 'absolute')}` : ''}
                      {invite.notBefore !== null ? ` · ${formatListTime(invite.notBefore, 'absolute')} 起生效` : ''}
                      {invite.expiresAt !== null ? ` · 过期于 ${formatListTime(invite.expiresAt, 'absolute')}` : ''}
                    </p>
                  </div>
                  {state.actionable && (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={revoke.isPending}
                      onClick={() =>
                        onConfirm({
                          title: '撤销这个邀请？',
                          body: '撤销后该链接立即失效；已创建的邀请无法恢复。',
                          confirmLabel: '撤销邀请',
                          action: () => revoke.mutateAsync(invite.id),
                        })
                      }
                    >
                      撤销
                    </Button>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </section>
  )
}

// ===== 邀请方案（N001）=======================================================

/** 批量生成对话框状态：方案 + 数量 + 一次性结果（token 只出现一次）。 */
interface BatchState {
  scheme: InviteScheme
}

function SchemesSection({ onConfirm }: { onConfirm: (state: ConfirmState) => void }) {
  const queryClient = useQueryClient()
  const schemes = useQuery({
    queryKey: ['admin', 'invite-schemes'],
    queryFn: ({ signal }) => listInviteSchemes(signal),
    staleTime: 10_000,
  })
  const [name, setName] = useState('')
  const [ttlHours, setTtlHours] = useState('72')
  const [sourceUrls, setSourceUrls] = useState('')
  const [poolHold, setPoolHold] = useState(false)
  const [quotaNote, setQuotaNote] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [batch, setBatch] = useState<BatchState | null>(null)
  const [batchCount, setBatchCount] = useState('1')
  const [batchError, setBatchError] = useState<string | null>(null)
  const [batchResult, setBatchResult] = useState<AdminInviteCreated[] | null>(null)

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['admin', 'invite-schemes'] })
    void queryClient.invalidateQueries({ queryKey: ['admin', 'funnel'] })
  }

  const create = useMutation({
    mutationFn: () =>
      createInviteScheme({
        name,
        ttlHours: ttlHours !== '' ? Number.parseInt(ttlHours, 10) : undefined,
        initialSourceUrls: sourceUrls
          .split('\n')
          .map((line) => line.trim())
          .filter((line) => line !== ''),
        freshrssPoolHold: poolHold,
        quotaNote: quotaNote !== '' ? quotaNote : null,
      }),
    onSuccess: () => {
      setName('')
      setTtlHours('72')
      setSourceUrls('')
      setPoolHold(false)
      setQuotaNote('')
      invalidate()
    },
    onError: (error) => setFormError(adminActionError(error)),
  })
  const generate = useMutation({
    mutationFn: (input: { schemeId: string; count: number }) =>
      generateInvitesFromScheme(input.schemeId, { count: input.count }),
    onSuccess: (result) => {
      setBatchResult(result.invites)
      void queryClient.invalidateQueries({ queryKey: ['admin', 'invites'] })
      void queryClient.invalidateQueries({ queryKey: ['admin', 'funnel'] })
    },
    onError: (error) => setBatchError(adminActionError(error)),
  })
  const remove = useMutation({
    mutationFn: (schemeId: string) => deleteInviteScheme(schemeId),
    onSuccess: () => invalidate(),
    onError: (error) => setFormError(adminActionError(error)),
  })

  const parsedBatchCount = Number.parseInt(batchCount, 10)

  return (
    <section aria-label="邀请方案">
      <SectionHeading
        title="邀请方案"
        hint="保存命名模板（有效期 / 初始订阅源 / 池名额预约 / 配额备注），批量生成互相独立的一次性邀请；激活时自动订阅初始源（失败不影响激活）。"
      />

      <form
        className="flex flex-col gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          setFormError(null)
          create.mutate()
        }}
        data-testid="scheme-create-form"
      >
        <div className="flex flex-wrap gap-2">
          <div className="min-w-36 flex-1">
            <label htmlFor="scheme-name" className="mb-1 block text-xs font-medium text-[var(--lumi-text-secondary)]">
              方案名称
            </label>
            <input
              id="scheme-name"
              type="text"
              value={name}
              maxLength={64}
              onChange={(e) => setName(e.target.value)}
              required
              placeholder="如：新人基础套餐"
              className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-sm text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)]"
            />
          </div>
          <div className="w-24">
            <label htmlFor="scheme-ttl" className="mb-1 block text-xs font-medium text-[var(--lumi-text-secondary)]">
              有效期（小时）
            </label>
            <input
              id="scheme-ttl"
              type="number"
              min={1}
              max={720}
              value={ttlHours}
              onChange={(e) => setTtlHours(e.target.value)}
              className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-sm text-[var(--lumi-text-primary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)]"
            />
          </div>
        </div>
        <div>
          <label htmlFor="scheme-urls" className="mb-1 block text-xs font-medium text-[var(--lumi-text-secondary)]">
            初始订阅源（每行一个 URL，可选）
          </label>
          <textarea
            id="scheme-urls"
            value={sourceUrls}
            rows={2}
            onChange={(e) => setSourceUrls(e.target.value)}
            placeholder={'https://example.com/feed.xml\nhttps://rss.example/rss.xml'}
            className="w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2 text-sm text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)]"
          />
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <label htmlFor="scheme-hold" className="flex min-h-11 items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
            <input
              id="scheme-hold"
              type="checkbox"
              checked={poolHold}
              onChange={(e) => setPoolHold(e.target.checked)}
              className="size-4"
            />
            生成时预约 FreshRSS 池名额
          </label>
          <div className="min-w-32 flex-1">
            <label htmlFor="scheme-quota" className="mb-1 block text-xs font-medium text-[var(--lumi-text-secondary)]">
              配额备注（可选）
            </label>
            <input
              id="scheme-quota"
              type="text"
              value={quotaNote}
              maxLength={200}
              onChange={(e) => setQuotaNote(e.target.value)}
              placeholder="如：每人 3 源"
              className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-sm text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)]"
            />
          </div>
          <Button type="submit" variant="secondary" disabled={create.isPending} className="min-h-11 self-end">
            <Plus aria-hidden className="size-4" />
            {create.isPending ? '保存中…' : '保存方案'}
          </Button>
        </div>
        {formError !== null && (
          <p role="alert" className="text-xs leading-relaxed text-[var(--lumi-danger)]">
            {formError}
          </p>
        )}
      </form>

      <div className="mt-3">
        {schemes.isPending ? (
          <div aria-busy="true">
            <Skeleton className="h-8 w-full" />
          </div>
        ) : schemes.isError ? (
          <p role="alert" className="text-sm text-[var(--lumi-danger)]">
            {adminActionError(schemes.error)}
          </p>
        ) : schemes.data.length === 0 ? (
          <p className="text-sm text-[var(--lumi-text-tertiary)]">还没有方案模板。</p>
        ) : (
          <ul className="flex flex-col divide-y divide-[var(--lumi-separator)]" data-testid="scheme-list">
            {schemes.data.map((scheme) => (
              <li key={scheme.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-1.5 text-sm text-[var(--lumi-text-primary)]">
                    <span className="truncate">{scheme.name}</span>
                    <span className={`${badgeBase} bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-tertiary)]`}>
                      {scheme.ttlHours} 小时
                    </span>
                    {scheme.freshrssPoolHold && (
                      <span className={`${badgeBase} bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]`}>预约池名额</span>
                    )}
                  </p>
                  <p className="mt-0.5 truncate text-xs text-[var(--lumi-text-tertiary)]">
                    {scheme.initialSourceUrls.length > 0
                      ? `${scheme.initialSourceUrls.length} 个初始源`
                      : '无初始源'}
                    {scheme.quotaNote !== null ? ` · ${scheme.quotaNote}` : ''}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setBatch({ scheme })
                      setBatchCount('1')
                      setBatchResult(null)
                      setBatchError(null)
                    }}
                    data-testid={`scheme-generate-${scheme.id}`}
                  >
                    <Layers aria-hidden className="size-4" />
                    批量生成
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={remove.isPending}
                    onClick={() =>
                      onConfirm({
                        title: `删除方案「${scheme.name}」？`,
                        body: '只删除模板；已生成的邀请和已激活的账号保留其方案记录（列表中诚实显示「已删方案」）。',
                        confirmLabel: '删除方案',
                        action: () => remove.mutateAsync(scheme.id),
                      })
                    }
                  >
                    <Trash2 aria-hidden className="size-4" />
                    删除
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <Dialog
        open={batch !== null}
        onClose={() => setBatch(null)}
        title={batch !== null ? `从「${batch.scheme.name}」批量生成邀请` : ''}
        footer={
          <Button variant="ghost" onClick={() => setBatch(null)}>
            关闭
          </Button>
        }
      >
        <div className="flex flex-col gap-3">
          <form
            className="flex items-end gap-2"
            onSubmit={(event) => {
              event.preventDefault()
              setBatchError(null)
              if (batch === null || !Number.isInteger(parsedBatchCount) || parsedBatchCount < 1) return
              generate.mutate({ schemeId: batch.scheme.id, count: parsedBatchCount })
            }}
            data-testid="scheme-batch-form"
          >
            <div className="w-28">
              <label htmlFor="batch-count" className="mb-1 block text-xs font-medium text-[var(--lumi-text-secondary)]">
                生成数量
              </label>
              <input
                id="batch-count"
                type="number"
                min={1}
                max={100}
                value={batchCount}
                onChange={(e) => setBatchCount(e.target.value)}
                className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-sm text-[var(--lumi-text-primary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)]"
              />
            </div>
            <Button type="submit" variant="primary" disabled={generate.isPending} className="min-h-11">
              {generate.isPending ? '生成中…' : '生成'}
            </Button>
          </form>
          {batchError !== null && (
            <p role="alert" className="text-xs leading-relaxed text-[var(--lumi-danger)]">
              {batchError}
            </p>
          )}
          {batchResult !== null && (
            <div className="flex flex-col gap-2">
              {batchResult.map((item) => (
                <OneTimeLink key={item.invite.id} url={activationLink(item.token)} />
              ))}
            </div>
          )}
        </div>
      </Dialog>
    </section>
  )
}

// ===== 账户与注册（P0-05 注册策略）=========================================
//
// 实例级公开注册开关（control DB 持久化，migration 0089）。真正的闸门
// 在服务端 POST /auth/register —— 这个开关只是改变它的策略输入；关掉
// 不影响已有账户，邀请链接照常可用。变更走 PUT，本地开关乐观先行，
// 失败回滚到服务端值并诚实提示；updatedAt/updatedBy 服务端没给就不显示。

function RegistrationPolicySection() {
  const queryClient = useQueryClient()
  const policy = useQuery({
    queryKey: ['admin', 'registration-policy'],
    queryFn: ({ signal }) => getRegistrationPolicy(signal),
    staleTime: 10_000,
  })
  // 乐观镜像：null = 无在途变更，显示服务端值；PUT 失败归 null 即回滚。
  const [optimistic, setOptimistic] = useState<boolean | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const update = useMutation({
    mutationFn: (allow: boolean) => updateRegistrationPolicy(allow),
    onSuccess: (result) => {
      setOptimistic(null)
      queryClient.setQueryData(['admin', 'registration-policy'], result)
    },
    onError: (error) => {
      setOptimistic(null)
      setActionError(adminActionError(error))
      void queryClient.invalidateQueries({ queryKey: ['admin', 'registration-policy'] })
    },
  })

  const serverAllow = policy.data?.allowPublicRegistration === true
  const allow = optimistic ?? serverAllow

  return (
    <section aria-label="账户与注册" data-testid="registration-policy">
      <SectionHeading
        title="账户与注册"
        hint="实例级注册策略；每次变更都会记入审计日志。"
      />
      {policy.isPending ? (
        <div aria-busy="true">
          <Skeleton className="h-12 w-full" />
        </div>
      ) : policy.isError ? (
        <p role="alert" className="text-sm leading-relaxed text-[var(--lumi-danger)]">
          {adminActionError(policy.error)}
        </p>
      ) : (
        <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <label
                htmlFor="registration-policy-switch"
                className="block text-sm font-medium text-[var(--lumi-text-primary)]"
              >
                公开注册
              </label>
              <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
                允许任何可以访问此 LumiRSS 实例的人创建普通成员账号。关闭后不会影响已有账户，邀请链接仍然可以使用。
              </p>
            </div>
            <Switch
              id="registration-policy-switch"
              label="公开注册"
              checked={allow}
              onCheckedChange={(next) => {
                setActionError(null)
                setOptimistic(next)
                update.mutate(next)
              }}
              disabled={update.isPending}
            />
          </div>
          <p className="mt-2 text-xs text-[var(--lumi-text-tertiary)]" data-testid="registration-policy-state">
            当前状态：{allow ? '已开放' : '已关闭'}
            {policy.data.updatedAt !== null && (
              <>
                {' · '}最近变更 {formatListTime(policy.data.updatedAt, 'absolute')}
              </>
            )}
            {policy.data.updatedBy !== null && <> · 由 {policy.data.updatedBy}</>}
          </p>
          {update.isPending && (
            <p role="status" className="mt-1 text-xs text-[var(--lumi-text-secondary)]">
              正在保存…
            </p>
          )}
          {actionError !== null && (
            <p role="alert" className="mt-1 text-xs leading-relaxed text-[var(--lumi-danger)]">
              {actionError}
            </p>
          )}
        </div>
      )}
    </section>
  )
}

// ===== 邀请漏斗（N004）=======================================================
//
// 计数全部来自服务端真实行聚合（GET /admin/invite-funnel），响应绝无
// 邀请码；创建/激活/撤销后由对应 mutation 失效 ['admin','funnel'] 缓存，
// 卡片随之刷新——没有本地快照。

const FUNNEL_CARDS: { key: 'generated' | 'pending' | 'activated' | 'expired' | 'revoked'; label: string }[] = [
  { key: 'generated', label: '已生成' },
  { key: 'pending', label: '待使用' },
  { key: 'activated', label: '已激活' },
  { key: 'expired', label: '已过期' },
  { key: 'revoked', label: '已撤销' },
]

function FunnelSection() {
  const schemes = useQuery({
    queryKey: ['admin', 'invite-schemes'],
    queryFn: ({ signal }) => listInviteSchemes(signal),
    staleTime: 10_000,
  })
  const [schemeFilter, setSchemeFilter] = useState('')
  const funnel = useQuery({
    queryKey: ['admin', 'funnel', schemeFilter],
    queryFn: ({ signal }) => getInviteFunnel(signal, schemeFilter !== '' ? schemeFilter : null),
    staleTime: 10_000,
  })

  return (
    <section aria-label="邀请漏斗" data-testid="invite-funnel">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <SectionHeading title="邀请漏斗" hint="按方案聚合的真实计数（不含邀请码）；创建 / 激活 / 撤销后自动刷新。" />
        <div className="w-44">
          <label htmlFor="funnel-scheme-filter" className="mb-1 block text-xs font-medium text-[var(--lumi-text-secondary)]">
            按方案筛选
          </label>
          <select
            id="funnel-scheme-filter"
            value={schemeFilter}
            onChange={(e) => setSchemeFilter(e.target.value)}
            data-testid="funnel-scheme-filter"
            className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-sm text-[var(--lumi-text-primary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)]"
          >
            <option value="">全部方案</option>
            {(schemes.data ?? []).map((scheme) => (
              <option key={scheme.id} value={scheme.id}>
                {scheme.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {funnel.isPending ? (
        <div aria-busy="true" className="flex flex-col gap-2">
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
        </div>
      ) : funnel.isError ? (
        <p role="alert" className="text-sm text-[var(--lumi-danger)]">
          {adminActionError(funnel.error)}
        </p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5" data-testid="funnel-cards">
            {FUNNEL_CARDS.map((card) => (
              <div
                key={card.key}
                className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2 text-center"
                data-testid={`funnel-${card.key}`}
              >
                <p className="text-lg font-semibold text-[var(--lumi-text-primary)]">{funnel.data.totals[card.key]}</p>
                <p className="text-xs text-[var(--lumi-text-tertiary)]">{card.label}</p>
              </div>
            ))}
          </div>
          {funnel.data.totals.failedActivation > 0 && (
            <p className="mt-2 text-xs text-[var(--lumi-text-tertiary)]" data-testid="funnel-failed-activation">
              激活失败尝试：{funnel.data.totals.failedActivation} 次（来自审计记录）
            </p>
          )}
          {funnel.data.byScheme.length > 0 && (
            <ul className="mt-3 flex flex-col divide-y divide-[var(--lumi-separator)]" data-testid="funnel-by-scheme">
              {funnel.data.byScheme.map((bucket) => (
                <li key={bucket.schemeId ?? 'adhoc'} className="flex flex-wrap items-center gap-x-2 gap-y-0.5 py-1.5 text-xs">
                  <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-primary)]">
                    {bucket.schemeName ?? '未分组（普通邀请）'}
                  </span>
                  <span className="text-[var(--lumi-text-tertiary)]">
                    生成 {bucket.generated} · 待用 {bucket.pending} · 激活 {bucket.activated}
                    {bucket.expired > 0 ? ` · 过期 ${bucket.expired}` : ''}
                    {bucket.revoked > 0 ? ` · 撤销 ${bucket.revoked}` : ''}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  )
}

// ===== FreshRSS 池 =========================================================

function PoolSection() {
  const queryClient = useQueryClient()
  const pool = useQuery({
    queryKey: ['admin', 'pool'],
    queryFn: ({ signal }) => getFreshRssPool(signal),
    staleTime: 10_000,
  })
  const [freshrssUsername, setFreshrssUsername] = useState('')
  const [freshrssBaseUrl, setFreshrssBaseUrl] = useState('')
  const [apiPassword, setApiPassword] = useState('')
  const [publicUrl, setPublicUrl] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [registered, setRegistered] = useState(false)

  const register = useMutation({
    mutationFn: () =>
      registerFreshRssPool({
        freshrssUsername,
        freshrssBaseUrl,
        apiPassword,
        publicUrl: publicUrl !== '' ? publicUrl : null,
      }),
    onSuccess: () => {
      setRegistered(true)
      setFreshrssUsername('')
      setFreshrssBaseUrl('')
      setApiPassword('')
      setPublicUrl('')
      void queryClient.invalidateQueries({ queryKey: ['admin', 'pool'] })
    },
    onError: (error) => setFormError(adminActionError(error)),
  })

  return (
    <section aria-label="FreshRSS 池">
      <SectionHeading
        title="FreshRSS 池"
        hint="登记部署侧已创建好的 FreshRSS 账号（API 密码只写不读）；新成员激活时自动绑定一个独立账号。"
      />

      {pool.isPending ? (
        <div aria-busy="true" className="flex flex-col gap-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : pool.isError ? (
        <p role="alert" className="text-sm text-[var(--lumi-danger)]">
          {adminActionError(pool.error)}
        </p>
      ) : (
        <>
          <p className="text-sm text-[var(--lumi-text-secondary)]" data-testid="pool-counts">
            可绑定 <span className="font-semibold text-[var(--lumi-text-primary)]">{pool.data.ready}</span> ·
            已预约 <span className="font-semibold text-[var(--lumi-text-primary)]">{pool.data.held}</span> ·
            已分配 <span className="font-semibold text-[var(--lumi-text-primary)]">{pool.data.assigned}</span>
          </p>

          <form
            className="mt-3 flex flex-col gap-2"
            onSubmit={(event) => {
              event.preventDefault()
              setFormError(null)
              setRegistered(false)
              register.mutate()
            }}
            data-testid="pool-register-form"
          >
            <div className="flex flex-wrap gap-2">
              <div className="min-w-32 flex-1">
                <label htmlFor="pool-username" className="mb-1 block text-xs font-medium text-[var(--lumi-text-secondary)]">
                  FreshRSS 用户名
                </label>
                <input
                  id="pool-username"
                  type="text"
                  value={freshrssUsername}
                  onChange={(e) => setFreshrssUsername(e.target.value)}
                  required
                  className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-sm text-[var(--lumi-text-primary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)]"
                />
              </div>
              <div className="min-w-40 flex-[2]">
                <label htmlFor="pool-base-url" className="mb-1 block text-xs font-medium text-[var(--lumi-text-secondary)]">
                  FreshRSS 地址
                </label>
                <input
                  id="pool-base-url"
                  type="url"
                  value={freshrssBaseUrl}
                  onChange={(e) => setFreshrssBaseUrl(e.target.value)}
                  placeholder="https://freshrss.example.com"
                  required
                  className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-sm text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)]"
                />
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <div className="min-w-32 flex-1">
                <label htmlFor="pool-api-password" className="mb-1 block text-xs font-medium text-[var(--lumi-text-secondary)]">
                  API 密码（只写）
                </label>
                <input
                  id="pool-api-password"
                  type="password"
                  value={apiPassword}
                  onChange={(e) => setApiPassword(e.target.value)}
                  required
                  autoComplete="new-password"
                  className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-sm text-[var(--lumi-text-primary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)]"
                />
              </div>
              <div className="min-w-32 flex-1">
                <label htmlFor="pool-public-url" className="mb-1 block text-xs font-medium text-[var(--lumi-text-secondary)]">
                  公网地址（可选）
                </label>
                <input
                  id="pool-public-url"
                  type="url"
                  value={publicUrl}
                  onChange={(e) => setPublicUrl(e.target.value)}
                  className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-sm text-[var(--lumi-text-primary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)]"
                />
              </div>
            </div>
            <Button
              type="submit"
              variant="secondary"
              disabled={register.isPending}
              className="min-h-11 self-start"
            >
              {register.isPending ? '登记中…' : '登记入池'}
            </Button>
            {registered && (
              <p role="status" className="text-xs text-[var(--lumi-accent-text)]">
                已登记入池。
              </p>
            )}
            {formError !== null && (
              <p role="alert" className="text-xs leading-relaxed text-[var(--lumi-danger)]">
                {formError}
              </p>
            )}
          </form>

          {pool.data.members.length > 0 && (
            <ul className="mt-3 flex flex-col divide-y divide-[var(--lumi-separator)]" data-testid="pool-member-list">
              {pool.data.members.map((member) => (
                <li key={member.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                  <span className="truncate text-[var(--lumi-text-primary)]">{member.username}</span>
                  {member.bound ? (
                    <span className="shrink-0 text-xs text-[var(--lumi-text-tertiary)]">
                      已绑定 {member.boundTo ?? ''}
                    </span>
                  ) : (
                    <span className={`${badgeBase} shrink-0 bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-tertiary)]`}>
                      待绑定
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  )
}

// ===== 系统面板（P11）=======================================================
//
// 数据全部来自 GET /admin/system（admin-only、服务端派生：版本/运行时/
// 内存、存储计数、服务健康、后台任务）与 GET /admin/audit（审计尾部）。
// 没有真实数据的字段如实显示「—」；每个状态都带文字标签（不只靠颜色）。
// 计数中的订阅/条目/资料库三项是「当前管理员自己库」的投影计数——
// 管理台没有、也不会有跨成员内容视图（0067 隔离不变式）。

const SERVICE_LABELS: Record<string, string> = {
  sqlite: 'Lumi 数据库',
  freshrss: 'FreshRSS',
  rsshub: 'RSSHub',
  obsidian: 'Obsidian 库',
  webdav: 'WebDAV 备份',
  ai: 'AI 服务',
  imap: 'IMAP 邮件',
}

const SERVICE_STATE_LABELS: Record<string, string> = {
  healthy: '正常',
  configured: '已配置',
  unconfigured: '未配置',
  unauthenticated: '认证失败',
  unavailable: '连接失败',
  unknown: '未知',
}

const TASK_LABELS: Record<string, string> = {
  search_sync: '订阅投影同步',
  obsidian_scan: 'Obsidian 扫描',
  digest_scheduler: '邮件日报调度',
  mail_imap: 'IMAP 轮询',
  gpt_digest_scheduler: 'GPT 日报调度',
  rag_idle: 'RAG 闲置卸载',
  rag_index: 'RAG 增量索引',
}

const TASK_STATE_LABELS: Record<string, string> = {
  running: '运行中',
  completed: '已结束',
  cancelled: '已取消',
  failed: '失败',
  off: '未启用',
  unknown: '未知',
}

const AUDIT_ACTION_LABELS: Record<string, string> = {
  invite_create_signup: '创建注册邀请',
  invite_create_recovery: '创建恢复邀请',
  invite_revoke: '撤销邀请',
  invite_scheme_create: '保存邀请方案',
  invite_scheme_delete: '删除邀请方案',
  invite_batch_generate: '批量生成邀请',
  user_paused: '暂停成员',
  user_resumed: '恢复成员',
  user_role_change: '变更角色',
  user_revoke_sessions: '撤销成员会话',
  user_password_reset: '重置成员密码',
  pool_add: '登记 FreshRSS 入池',
}

function auditActionLabel(action: string): string {
  return AUDIT_ACTION_LABELS[action] ?? action
}

function formatBytes(bytes: number | null): string {
  if (bytes === null) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${unit === 0 || value >= 100 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`
}

function formatUptime(seconds: number | null): string {
  if (seconds === null) return '—'
  const days = Math.floor(seconds / 86_400)
  const hours = Math.floor((seconds % 86_400) / 3_600)
  const minutes = Math.floor((seconds % 3_600) / 60)
  if (days > 0) return `${days} 天 ${hours} 小时`
  if (hours > 0) return `${hours} 小时 ${minutes} 分`
  return `${minutes} 分`
}

const stateBadge = (_text: string, tone: 'ok' | 'warn' | 'muted'): string =>
  `${badgeBase} ${
    tone === 'ok'
      ? 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]'
      : tone === 'warn'
        ? 'bg-[var(--lumi-danger)] text-[var(--lumi-danger-contrast)]'
        : 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-tertiary)]'
  }`

function SystemRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="shrink-0 text-xs text-[var(--lumi-text-tertiary)]">{label}</span>
      <span className="min-w-0 truncate text-sm font-medium text-[var(--lumi-text-primary)]">{value}</span>
    </div>
  )
}

function serviceTone(status: string): 'ok' | 'warn' | 'muted' {
  if (status === 'healthy' || status === 'configured' || status === 'running') return 'ok'
  if (status === 'unavailable' || status === 'unauthenticated' || status === 'failed') return 'warn'
  return 'muted'
}

function SystemSection() {
  const system = useQuery({
    queryKey: ['admin', 'system'],
    queryFn: ({ signal }) => getAdminSystem(signal),
    staleTime: 10_000,
  })
  const audit = useQuery({
    queryKey: ['admin', 'audit'],
    queryFn: ({ signal }) => listAdminAudit(signal),
    staleTime: 10_000,
  })
  const refreshing = system.isFetching || audit.isFetching

  return (
    <section aria-label="系统状态" data-testid="admin-system">
      <div className="mb-3 flex items-start justify-between gap-3">
        <SectionHeading title="系统" hint="部署诊断（服务端派生，不含秘密值）与最近操作记录。" />
        <Button
          size="sm"
          variant="ghost"
          className="min-h-11"
          disabled={refreshing}
          onClick={() => {
            void system.refetch()
            void audit.refetch()
          }}
          aria-label="刷新系统状态"
          data-testid="admin-system-refresh"
        >
          <RefreshCw aria-hidden className="size-4" />
          {refreshing ? '刷新中…' : '刷新'}
        </Button>
      </div>

      {system.isPending ? (
        <div aria-busy="true" className="flex flex-col gap-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : system.isError ? (
        <p role="alert" className="text-sm leading-relaxed text-[var(--lumi-danger)]">
          {adminActionError(system.error)}
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {/* 版本与运行时 */}
          <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3" data-testid="admin-system-runtime">
            <p className="mb-1.5 text-xs font-semibold text-[var(--lumi-text-secondary)]">版本与运行时</p>
            <SystemRow label="版本" value={`${system.data.version}${system.data.commit !== '' ? ` (${system.data.commit.slice(0, 7)})` : ''}`} />
            <SystemRow label="Python" value={system.data.python !== '' ? system.data.python : '—'} />
            <SystemRow label="运行时长" value={formatUptime(system.data.uptimeS)} />
            <SystemRow label="内存（当前 / 峰值）" value={`${formatBytes(system.data.process.rssBytes)} / ${formatBytes(system.data.process.peakRssBytes)}`} />
            <SystemRow
              label="CPU 累计"
              value={system.data.process.cpuTimeS !== null ? `${system.data.process.cpuTimeS.toFixed(1)} 秒` : '—'}
            />
          </div>

          {/* 存储计数 */}
          <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3" data-testid="admin-system-counts">
            <p className="mb-1.5 text-xs font-semibold text-[var(--lumi-text-secondary)]">存储计数</p>
            <SystemRow label="成员（活跃）" value={`${system.data.counts.users}（${system.data.counts.activeUsers}）`} />
            <SystemRow label="邀请记录" value={String(system.data.counts.invites)} />
            <SystemRow label="FreshRSS 池（可绑定 / 已分配）" value={`${system.data.counts.freshrssPoolReady} / ${system.data.counts.freshrssPoolAssigned}`} />
            <SystemRow label="活跃会话" value={String(system.data.counts.sessions)} />
            <SystemRow
              label="我的订阅 / 条目 / 资料库"
              value={`${system.data.counts.feeds} / ${system.data.counts.entriesIndexed} / ${system.data.counts.libraryItems}`}
            />
          </div>

          {/* 服务健康 */}
          <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3" data-testid="admin-system-services">
            <p className="mb-1.5 text-xs font-semibold text-[var(--lumi-text-secondary)]">服务状态</p>
            <ul className="flex flex-col divide-y divide-[var(--lumi-separator)]">
              {system.data.services.map((service) => (
                <li key={service.name} className="flex items-center justify-between gap-3 py-1.5">
                  <span className="min-w-0 truncate text-sm text-[var(--lumi-text-primary)]">
                    {SERVICE_LABELS[service.name] ?? service.name}
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    {service.latencyMs !== null && (
                      <span className="text-xs text-[var(--lumi-text-tertiary)]">{service.latencyMs} ms</span>
                    )}
                    <span className={stateBadge(SERVICE_STATE_LABELS[service.status] ?? service.status, serviceTone(service.status))}>
                      {SERVICE_STATE_LABELS[service.status] ?? service.status}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </div>

          {/* 后台任务 */}
          <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3" data-testid="admin-system-tasks">
            <p className="mb-1.5 text-xs font-semibold text-[var(--lumi-text-secondary)]">后台任务</p>
            <ul className="flex flex-col divide-y divide-[var(--lumi-separator)]">
              {system.data.tasks.map((task) => (
                <li key={task.name} className="flex items-center justify-between gap-3 py-1.5">
                  <span className="min-w-0 truncate text-sm text-[var(--lumi-text-primary)]">
                    {TASK_LABELS[task.name] ?? task.name}
                  </span>
                  <span className={stateBadge(TASK_STATE_LABELS[task.state] ?? task.state, serviceTone(task.state))}>
                    {TASK_STATE_LABELS[task.state] ?? task.state}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          {/* 最近动态（审计尾部；API 已脱敏：操作者只以 id 出现） */}
          <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3 md:col-span-2" data-testid="admin-system-audit">
            <p className="mb-1.5 text-xs font-semibold text-[var(--lumi-text-secondary)]">最近动态</p>
            {audit.isPending ? (
              <div aria-busy="true" className="flex flex-col gap-2">
                <Skeleton className="h-6 w-full" />
                <Skeleton className="h-6 w-4/5" />
              </div>
            ) : audit.isError ? (
              <p role="alert" className="text-xs leading-relaxed text-[var(--lumi-danger)]">
                {adminActionError(audit.error)}
              </p>
            ) : audit.data.length === 0 ? (
              <p className="text-sm text-[var(--lumi-text-tertiary)]">暂无操作记录。</p>
            ) : (
              <ul className="flex flex-col divide-y divide-[var(--lumi-separator)]" data-testid="admin-audit-list">
                {audit.data.map((entry, index) => (
                  <li key={`${entry.at ?? 'na'}-${entry.action}-${index}`} className="flex flex-wrap items-center gap-x-2 gap-y-0.5 py-1.5 text-sm">
                    <span className="text-[var(--lumi-text-primary)]">{auditActionLabel(entry.action)}</span>
                    <span className="text-xs text-[var(--lumi-text-tertiary)]">
                      {formatRelativeTime(entry.at)}
                      {entry.detail !== null ? ` · ${entry.detail}` : ''}
                    </span>
                    {entry.outcome !== 'ok' && (
                      <span className={stateBadge(entry.outcome, 'warn')}>{entry.outcome}</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </section>
  )
}

// ===== 页面骨架 ============================================================

export default function AdminScreen() {
  const identity = useAuthStore((s) => s.identity)
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null)
  const [confirmError, setConfirmError] = useState<string | null>(null)
  const [confirmPending, setConfirmPending] = useState(false)

  const forbidden =
    identity === null
      ? 'hidden'
      : identity.role === 'owner' || identity.role === 'admin'
        ? null
        : 'denied'

  return (
    <div className="min-h-dvh overflow-y-auto bg-[var(--lumi-canvas)]" data-testid="admin-screen">
      <div className="mx-auto w-full max-w-5xl px-4 py-6">
        <div className="mb-5 flex items-center gap-3">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigateAppRoute('app')}
            aria-label="返回阅读"
            data-testid="admin-back"
          >
            <ArrowLeft aria-hidden className="size-4" />
            返回
          </Button>
          <h1 className="text-lg font-semibold tracking-tight text-[var(--lumi-text-primary)]">管理台</h1>
        </div>

        {forbidden === 'denied' ? (
          <div
            role="alert"
            data-testid="admin-forbidden"
            className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-6 text-center"
          >
            <p className="text-sm font-medium text-[var(--lumi-text-primary)]">没有访问权限</p>
            <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
              管理台仅对运营者与管理员开放。如需权限，请联系运营者。
            </p>
          </div>
        ) : forbidden === 'hidden' ? (
          <p role="status" className="text-sm text-[var(--lumi-text-secondary)]">
            正在核实身份…
          </p>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 lg:items-start">
              <div className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-4">
                <MembersSection onConfirm={setConfirmState} />
              </div>
              <div className="flex flex-col gap-4">
                <div className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-4">
                  <InvitesSection onConfirm={setConfirmState} />
                </div>
                <div className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-4">
                  <RegistrationPolicySection />
                </div>
                <div className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-4">
                  <PoolSection />
                </div>
              </div>
            </div>
            <div className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-4">
              <FunnelSection />
            </div>
            <div className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-4">
              <SchemesSection onConfirm={setConfirmState} />
            </div>
            <div className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-4">
              <SystemSection />
            </div>
          </div>
        )}
      </div>

      {/* 危险操作统一确认（Base UI Dialog 拥有 Escape/焦点陷阱/滚动锁） */}
      <Dialog
        open={confirmState !== null}
        onClose={() => setConfirmState(null)}
        title={confirmState?.title ?? ''}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmState(null)}>
              取消
            </Button>
            <Button
              variant="danger"
              disabled={confirmPending}
              onClick={() => {
                if (confirmState === null) return
                setConfirmPending(true)
                setConfirmError(null)
                confirmState
                  .action()
                  .then(() => setConfirmState(null))
                  .catch((error: unknown) => setConfirmError(adminActionError(error)))
                  .finally(() => setConfirmPending(false))
              }}
            >
              {confirmPending ? '执行中…' : confirmState?.confirmLabel ?? '确认'}
            </Button>
          </>
        }
      >
        <p className="text-sm leading-relaxed text-[var(--lumi-text-primary)]">{confirmState?.body}</p>
        {confirmError !== null && (
          <p role="alert" className="mt-2 text-xs leading-relaxed text-[var(--lumi-danger)]">
            {confirmError}
          </p>
        )}
      </Dialog>
    </div>
  )
}
