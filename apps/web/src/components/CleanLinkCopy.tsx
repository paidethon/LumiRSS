/** F010 复制干净链接 —— 差异预览对话框 + 外链上下文菜单装饰。
 *
 * 预览最小差异（将移除的参数名列表）→ 用户确认才写剪贴板；取消 =
 * 不发生任何复制。签名/未知参数绝不静默移除（见 lib/tracking-params）。 */

import { useState } from 'react'
import { Check, Copy, Link2Off } from 'lucide-react'
import { stripTrackingParams } from '../lib/tracking-params'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'

/** 差异预览对话框：列出将被移除的参数；确认复制 / 取消。 */
export function CleanLinkPreviewDialog({
  open,
  url,
  onClose,
}: {
  open: boolean
  url: string | null
  onClose: () => void
}) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')
  const cleaned = url !== null ? stripTrackingParams(url) : null
  const removed = cleaned?.removed ?? []

  function close() {
    setState('idle')
    onClose()
  }

  async function confirmCopy() {
    if (cleaned === null) return
    try {
      await navigator.clipboard.writeText(cleaned.url)
      setState('copied')
      window.setTimeout(() => close(), 900)
    } catch {
      setState('failed')
    }
  }

  return (
    <Dialog
      open={open && url !== null}
      onClose={close}
      title="复制干净链接"
      footer={
        <>
          <Button variant="ghost" onClick={close}>
            取消
          </Button>
          <Button variant="primary" onClick={() => void confirmCopy()} disabled={url === null}>
            <Copy aria-hidden className="size-4" />
            {state === 'copied' ? '已复制' : '确认复制'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="text-sm text-[var(--lumi-text-secondary)]">
          将移除以下追踪参数（{removed.length} 个）；其余参数与签名类参数保持不变。
        </p>
        {removed.length === 0 ? (
          <p className="rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-selected)] px-3 py-2 text-xs text-[var(--lumi-text-tertiary)]">
            该链接没有可移除的追踪参数，将原样复制。
          </p>
        ) : (
          <ul
            data-testid="removed-params"
            className="flex flex-wrap gap-1.5"
            aria-label="将移除的追踪参数"
          >
            {removed.map((name) => (
              <li
                key={name}
                className="rounded-full bg-[var(--lumi-danger)]/10 px-2 py-0.5 text-xs text-[var(--lumi-danger)]"
              >
                {name}
              </li>
            ))}
          </ul>
        )}
        {cleaned !== null && (
          <p className="break-all text-xs text-[var(--lumi-text-tertiary)]" data-testid="clean-url-preview">
            清理后：{cleaned.url}
          </p>
        )}
        {state === 'failed' && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            复制失败：请检查浏览器剪贴板权限后重试。
          </p>
        )}
      </div>
    </Dialog>
  )
}

/** 渲染后装饰（幂等）：给正文外链挂右键 / 长按菜单（复制链接 /
 * 复制干净链接）。返回清理函数（容器卸载/重渲染时移除监听）。 */
export function attachExternalLinkMenu(
  container: HTMLElement,
  openMenu: (url: string, x: number, y: number) => void,
): () => void {
  const cleanupFns: (() => void)[] = []
  for (const anchor of Array.from(container.querySelectorAll('a[href]'))) {
    const href = anchor.getAttribute('href')
    if (href === null || !/^https?:\/\//i.test(href)) continue
    const el = anchor as HTMLElement
    const onContextMenu = (event: MouseEvent) => {
      event.preventDefault()
      openMenu(href, event.clientX, event.clientY)
    }
    // 长按（移动端）：500ms 触发，按下移动/松开取消
    let timer: number | null = null
    const clearTimer = () => {
      if (timer !== null) {
        window.clearTimeout(timer)
        timer = null
      }
    }
    const onTouchStart = (event: TouchEvent) => {
      const touch = event.touches[0]
      if (touch === undefined) return
      const { clientX, clientY } = touch
      timer = window.setTimeout(() => openMenu(href, clientX, clientY), 500)
    }
    el.addEventListener('contextmenu', onContextMenu)
    el.addEventListener('touchstart', onTouchStart, { passive: true })
    el.addEventListener('touchmove', clearTimer, { passive: true })
    el.addEventListener('touchend', clearTimer)
    cleanupFns.push(() => {
      el.removeEventListener('contextmenu', onContextMenu)
      el.removeEventListener('touchstart', onTouchStart)
      el.removeEventListener('touchmove', clearTimer)
      el.removeEventListener('touchend', clearTimer)
    })
  }
  return () => cleanupFns.forEach((fn) => fn())
}

/** 复制动作图标（菜单项内部使用）。 */
export function CopyActionIcon({ clean }: { clean: boolean }) {
  return clean ? <Link2Off aria-hidden className="size-3.5" /> : <Check aria-hidden className="size-3.5" />
}
