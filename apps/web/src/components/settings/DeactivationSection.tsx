/** DeactivationSection — N190 账户停用（设置 → 账户与服务）。
 *
 * 用户发起停用：密码复核 → 状态置 pending_deletion（宽限期默认 14
 * 天）→ 全部会话立即吊销（本设备登出）。诚实口径三条，界面明示：
 * - 宽限期内运营者可在管理台「恢复」；
 * - 到期后没有自动删除作业，物理删除由运营者手动执行；
 * - 数据迁出用 设置 → 数据控制 的迁出向导（N010）。
 */

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, getDeactivationStatus, requestAccountDeactivation } from '../../api/client'
import { Button } from '../ui/Button'

export function DeactivationSection({ onDeactivated }: { onDeactivated: () => void }) {
  const [confirming, setConfirming] = useState(false)
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  // 当前状态（若已处于 pending_deletion，这里会如实展示计划删除时间）。
  const status = useQuery({
    queryKey: ['me-deactivation'],
    queryFn: ({ signal }) => getDeactivationStatus(signal),
    staleTime: 0,
    retry: false,
  })

  if (status.data?.requested === true) {
    return (
      <section
        aria-label="账户停用"
        data-testid="deactivation-section"
        className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3"
      >
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">账户停用</h3>
        <p role="status" data-testid="deactivation-status" className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          停用请求已提交：数据将于 {status.data.scheduledDeletionAt ?? '（未知时间）'} 后由运营者手动删除。
          宽限期内可联系运营者恢复（管理台「恢复」即撤销停用）。
        </p>
        <p className="text-xs text-[var(--lumi-text-tertiary)]">{status.data.exportHint}</p>
      </section>
    )
  }

  return (
    <section
      aria-label="账户停用"
      data-testid="deactivation-section"
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3"
    >
      <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">账户停用</h3>
      {!confirming ? (
        <>
          <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
            停用后立即退出登录，账号在宽限期（14 天）内不可登录；宽限期内运营者可恢复。
            到期后没有自动删除作业——物理删除由运营者手动执行。
          </p>
          <div>
            <Button variant="danger" size="sm" onClick={() => setConfirming(true)}>
              停用我的账户…
            </Button>
          </div>
        </>
      ) : (
        <div className="flex flex-col gap-2">
          <p className="text-xs text-[var(--lumi-text-danger, #dc2626)]">
            请输入当前密码确认。建议先完成数据迁出（设置 → 数据控制 → 迁出向导）。
          </p>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-label="确认密码（停用账户）"
            data-testid="deactivation-password"
            autoComplete="current-password"
            className="min-h-10 w-full max-w-xs rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-sm"
          />
          <div className="flex items-center gap-2">
            <Button
              variant="danger"
              size="sm"
              data-testid="deactivation-confirm"
              disabled={password === '' || pending}
              onClick={async () => {
                setPending(true)
                setError(null)
                try {
                  await requestAccountDeactivation(password)
                  // 服务端已吊销全部会话 → 本地清理 + 回登录门。
                  onDeactivated()
                } catch (err) {
                  if (err instanceof ApiError && err.type === 'invalid_credentials') {
                    setError('密码不正确。')
                  } else if (err instanceof ApiError && err.type === 'owner_undeactivatable') {
                    setError('owner 账户不支持自助停用。')
                  } else {
                    setError('停用请求失败，请稍后重试。')
                  }
                } finally {
                  setPending(false)
                }
              }}
            >
              {pending ? '提交中…' : '确认停用'}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setConfirming(false)
                setError(null)
              }}
            >
              取消
            </Button>
          </div>
          {error !== null && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">{error}</p>
          )}
        </div>
      )}
    </section>
  )
}
