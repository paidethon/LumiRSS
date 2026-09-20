/** CheckLinksDialog — F087 书签失效检查（多选「检查链接」入口）。
 *
 * 并发探测（服务端 ≤4、HEAD→有界 GET、8s 超时、SSRF 校验）；结果按状态
 * 分类渲染；「仅复查失败」只重发失败 ref。检查是纯读：书签 URL 永不
 * 改写（redirect 只报告 finalUrl）。
 */

import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { checkBookmarkLinks, type BookmarkCheckItem, type BookmarkLinkStatus } from '../api/client'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'

export const LINK_STATUS_LABELS: Record<BookmarkLinkStatus, string> = {
  ok: '正常',
  redirect: '重定向',
  not_found: '不存在（404）',
  auth_required: '需要登录',
  rate_limited: '被限流',
  timeout: '超时',
  network_error: '网络错误',
  blocked_ssrf: '已拦截（内网地址）',
}

export function CheckLinksDialog({ refs, onClose }: { refs: string[]; onClose: () => void }) {
  const [items, setItems] = useState<BookmarkCheckItem[] | null>(null)
  const check = useMutation({
    mutationFn: (onlyRefs: string[] | null) => checkBookmarkLinks(onlyRefs ?? refs),
    onSuccess: (data, onlyRefs) => {
      setItems((prev) => {
        if (onlyRefs === null || prev === null) return data.items
        // 复查合并：仅替换本次复查的 ref，其余保留上次结果。
        const byRef = new Map(prev.map((i) => [i.ref, i]))
        for (const item of data.items) byRef.set(item.ref, item)
        return [...byRef.values()]
      })
    },
  })

  const failedRefs = (items ?? []).filter((i) => i.status !== 'ok' && i.status !== 'redirect').map((i) => i.ref)

  return (
    <Dialog
      open
      onClose={onClose}
      title={`检查链接（已选 ${refs.length} 条）`}
      panelClassName="max-w-xl"
      footer={
        <div className="flex w-full items-center gap-2">
          {items !== null && failedRefs.length > 0 && (
            <Button
              variant="secondary"
              size="sm"
              disabled={check.isPending}
              onClick={() => check.mutate(failedRefs)}
            >
              仅复查失败（{failedRefs.length}）
            </Button>
          )}
          <div className="ml-auto">
            <Button variant="ghost" size="sm" onClick={onClose}>关闭</Button>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-3" data-check-links="">
        <p className="text-xs text-[var(--lumi-text-secondary)]">
          只检查不修改：书签保存的 URL 永远保持原样（重定向只报告最终地址）。
        </p>
        {check.isPending && <p className="text-xs text-[var(--lumi-text-tertiary)]">检查中…</p>}
        {items === null && !check.isPending && (
          <div className="flex justify-center">
            <Button variant="primary" size="sm" onClick={() => check.mutate(null)}>
              开始检查
            </Button>
          </div>
        )}
        {check.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            检查失败：{check.error instanceof Error ? check.error.message : '请稍后重试。'}
          </p>
        )}
        {items !== null && (
          <ul className="flex max-h-72 flex-col gap-1.5 overflow-y-auto" data-check-results="">
            {items.map((item) => (
              <li
                key={item.ref}
                data-check-ref={item.ref}
                data-check-status={item.status}
                className="flex items-center justify-between gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1.5 text-xs"
              >
                <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-primary)]">{item.ref}</span>
                <span className="shrink-0 text-[var(--lumi-text-secondary)]">
                  {LINK_STATUS_LABELS[item.status] ?? item.status}
                  {item.httpStatus != null ? ` · HTTP ${item.httpStatus}` : ''}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Dialog>
  )
}
