/** AccountProfileSection — 设置 → 账户：本人身份卡（R03 账户/服务拆分）。
 *
 * 只展示服务端核实的身份（store/auth.ts 的 AuthIdentity —— GET
 * /auth/session 返回，绝不取自客户端声明）：用户名 + 角色徽标。
 * 头像 / 显示名 / 邮箱后端尚无对应字段与编辑端点，这里不伪造
 * （缺口如实标注，见 R17/R03 报告）。
 *
 * basic 模式：认证由代理层负责，无 Lumi 账户身份 —— 如实说明，
 * 不渲染误导性表单（与 AccountSecuritySection 的降级口径一致）。 */

import { Fingerprint, ShieldCheck, UserRound } from 'lucide-react'
import { useAuthStore } from '../../store/auth'
import { cx } from '../ui/cx'

const ROLE_LABELS: Record<string, string> = {
  owner: '运营者',
  admin: '管理员',
  member: '成员',
}

export function AccountProfileSection() {
  const mode = useAuthStore((s) => s.mode)
  const identity = useAuthStore((s) => s.identity)

  if (mode !== 'session') {
    return (
      <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        当前认证由代理层（basic 模式）负责，无 Lumi 账户资料可管理。
      </p>
    )
  }

  return (
    <div
      className="flex items-center gap-3 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-3.5 py-3"
      data-lumi-account-profile=""
    >
      <span
        aria-hidden="true"
        className="flex size-10 shrink-0 items-center justify-center rounded-full bg-[var(--lumi-accent-soft)]"
      >
        <UserRound className="size-5 text-[var(--lumi-accent-text)]" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-sm font-medium text-[var(--lumi-text-primary)]">
            {identity?.username ?? '身份核实中…'}
          </p>
          {identity !== null && (
            <span
              data-lumi-account-role=""
              className={cx(
                'shrink-0 rounded-[var(--lumi-radius-full)] px-2 py-0.5 text-[11px]',
                identity.role === 'owner'
                  ? 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]'
                  : 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-secondary)]',
              )}
            >
              {ROLE_LABELS[identity.role] ?? identity.role}
            </span>
          )}
        </div>
        <p className="mt-0.5 flex items-center gap-1 text-xs text-[var(--lumi-text-tertiary)]">
          <Fingerprint aria-hidden="true" className="size-3" />
          {identity?.userId !== undefined && identity.userId !== ''
            ? `账户 ID ${identity.userId}`
            : '身份以服务端会话核实为准'}
        </p>
      </div>
      <ShieldCheck
        aria-hidden="true"
        className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]"
      />
    </div>
  )
}
