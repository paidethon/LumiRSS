/** ViewFeedTokenDialog — F061 保存视图私有 Atom 订阅管理。
 *
 * - 未启用：说明 + 「启用私有订阅」→ 生成 token，完整 URL 仅本次展示
 *   （复制入口）；关闭后不可再查看，只能轮换；
 * - 已启用：「已隐藏，可轮换」+ 轮换（两步确认：旧地址立即失效）；
 * - token 本身绝不随管理端 API 返回（服务端契约），UI 也只在刚
 *   获得 atomPath 的会话态里展示它。 */

import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Check, Copy, Rss } from 'lucide-react'
import { Dialog } from './ui/Dialog'
import { Button } from './ui/Button'
import { enableViewFeedToken, rotateViewFeedToken } from '../api/client'

/** 本地错误文案（Error.message / 安全兜底）。 */
function errMsg(error: unknown): string {
  return error instanceof Error ? error.message : '请稍后重试。'
}

function absoluteUrl(atomPath: string): string {
  if (typeof window === 'undefined') return atomPath
  try {
    return new URL(atomPath, window.location.origin).toString()
  } catch {
    return atomPath
  }
}

export function ViewFeedTokenDialog({
  open,
  onClose,
  view,
}: {
  open: boolean
  onClose: () => void
  view: { id: string; name: string; hasFeedToken: boolean } | null
}) {
  const [revealedPath, setRevealedPath] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [confirmingRotate, setConfirmingRotate] = useState(false)

  useEffect(() => {
    // 换视图/关闭 → 清理会话态（隐藏过的地址不复活）。
    setRevealedPath(null)
    setCopied(false)
    setConfirmingRotate(false)
  }, [open, view?.id])

  const tokenMutation = useMutation({
    mutationFn: (action: 'enable' | 'rotate') =>
      action === 'enable' ? enableViewFeedToken(view?.id ?? '') : rotateViewFeedToken(view?.id ?? ''),
    onSuccess: (result) => {
      setRevealedPath(result.atomPath)
      setConfirmingRotate(false)
      setCopied(false)
    },
  })

  if (view === null) return null

  const handleCopy = async () => {
    if (revealedPath === null) return
    try {
      await navigator.clipboard.writeText(absoluteUrl(revealedPath))
      setCopied(true)
    } catch {
      // 剪贴板不可用（非安全上下文等）：保留 URL 可见可手选
      setCopied(false)
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={`私有订阅 — ${view.name}`}>
      <div className="flex flex-col gap-3">
        {revealedPath !== null ? (
          <>
            <p className="text-xs text-[var(--lumi-text-secondary)]">
              订阅地址已生成。完整地址仅展示这一次，关闭后不可再查看；
              请立即复制保存到你的 RSS 阅读器。
            </p>
            <input
              readOnly
              value={absoluteUrl(revealedPath)}
              aria-label="订阅地址（仅展示一次）"
              onFocus={(e) => e.currentTarget.select()}
              className="w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 font-mono text-xs text-[var(--lumi-text-primary)]"
            />
            <div className="flex items-center gap-2">
              <Button size="sm" variant="secondary" onClick={handleCopy}>
                {copied ? <Check aria-hidden className="size-3.5" /> : <Copy aria-hidden className="size-3.5" />}
                {copied ? '已复制' : '复制地址'}
              </Button>
              <span className="text-xs text-[var(--lumi-text-tertiary)]">
                已隐藏，可轮换（旧地址立即失效）
              </span>
            </div>
          </>
        ) : view.hasFeedToken ? (
          <>
            <p className="text-xs text-[var(--lumi-text-secondary)]">
              私有订阅已启用。完整地址已隐藏，可轮换生成新地址；
              轮换后旧地址立即失效（已订阅的读者需要更新）。
            </p>
            {confirmingRotate ? (
              <div className="flex flex-col gap-2 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface)] p-2.5">
                <span className="text-xs font-medium text-[var(--lumi-text-primary)]">
                  确认轮换？旧订阅地址将立即失效。
                </span>
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="primary"
                    disabled={tokenMutation.isPending}
                    onClick={() => tokenMutation.mutate('rotate')}
                  >
                    确认轮换
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setConfirmingRotate(false)}>
                    取消
                  </Button>
                </div>
              </div>
            ) : (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => setConfirmingRotate(true)}
                className="self-start"
              >
                轮换地址
              </Button>
            )}
          </>
        ) : (
          <>
            <p className="text-xs text-[var(--lumi-text-secondary)]">
              为该视图生成私有 Atom 订阅：按视图的搜索条件与筛选实时输出
              （≤100 条）。地址含随机密钥，无需登录即可订阅；
              完整地址仅生成时展示一次。
            </p>
            <Button
              size="sm"
              variant="primary"
              disabled={tokenMutation.isPending}
              onClick={() => tokenMutation.mutate('enable')}
              className="self-start"
            >
              <Rss aria-hidden className="size-3.5" />
              {tokenMutation.isPending ? '生成中…' : '启用私有订阅'}
            </Button>
          </>
        )}
        {tokenMutation.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {errMsg(tokenMutation.error)}
          </p>
        )}
      </div>
    </Dialog>
  )
}
