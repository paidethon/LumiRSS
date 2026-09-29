/** LinkActionSheet — NEW-358 链接操作面板（长按外链弹出；底部 Sheet）。
 *
 * 展示域名与完整地址，提供：复制链接 / 复制净链接（去跟踪参数）/
 * 稍后打开（本机暂存清单）/ 剪藏（一次性预填交接，跳转剪藏页确认）。
 * **本面板零网络**：不做任何远端预览/测量请求——打开与抓取都只发生
 * 在用户显式的下一步动作里（新标签打开 / 剪藏页确认）。
 *
 * 长按手势（LinkActionGesture）用事件委托挂在正文容器上：550ms 长按
 * 外链弹出本面板；移动/抬起取消，弹出不吞掉后续普通点击之外的行为。 */

import { useEffect, useRef, useState } from 'react'

/** 长按判定时长（ms；与触控长按菜单惯值一致）。 */
export const LINK_LONG_PRESS_MS = 550
import { Sheet } from '../ui/Sheet'
import { stripTrackingParams } from '../../lib/tracking-params'
import {
  addLinkLater,
  isExternalHttpUrl,
  linkDomain,
  readLinkLater,
  removeLinkLater,
  stageClipPrefill,
  type LinkLaterItem,
} from '../../lib/link-actions'
import { useReaderUi } from '../../store/reader-ui'
import { IconButton } from '../ui/IconButton'
import { Check, ClipboardCopy, ExternalLink, Hourglass, Link2Off, Scissors, X } from 'lucide-react'

export interface LinkActionSheetProps {
  /** 当前操作的绝对 URL（null = 关闭）。 */
  url: string | null
  onClose: () => void
}

export function LinkActionSheet({ url, onClose }: LinkActionSheetProps) {
  const selectSection = useReaderUi((s) => s.selectSection)
  const [copied, setCopied] = useState<'plain' | 'clean' | null>(null)
  const [laterItems, setLaterItems] = useState<LinkLaterItem[]>(() => readLinkLater())
  const [clipStaged, setClipStaged] = useState(false)
  const copyTimer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(copyTimer.current), [])

  if (url === null) return null
  const domain = linkDomain(url)
  const isLater = laterItems.some((item) => item.url === url)

  const flashCopy = (kind: 'plain' | 'clean') => {
    setCopied(kind)
    window.clearTimeout(copyTimer.current)
    copyTimer.current = window.setTimeout(() => setCopied(null), 1500)
  }

  const copy = async (kind: 'plain' | 'clean') => {
    const cleaned = kind === 'clean' ? stripTrackingParams(url) : null
    const text = cleaned !== null ? cleaned.url : url
    try {
      await navigator.clipboard.writeText(text)
      flashCopy(kind)
    } catch {
      // 剪贴板不可用：不假装成功。
    }
  }

  const toggleLater = () => {
    if (isLater) removeLinkLater(url)
    else addLinkLater(url)
    setLaterItems(readLinkLater())
  }

  const openLater = (target: string) => {
    window.open(target, '_blank', 'noopener,noreferrer')
  }

  const stageClip = () => {
    // 已授权剪藏操作 = 一次性预填交接（与 PWA Share Target 同一通道）；
    // 抓取只发生在剪藏页用户显式确认后——此处绝不发起远端预览请求。
    if (stageClipPrefill(url)) {
      setClipStaged(true)
      selectSection('clips')
      onClose()
    }
  }

  const cleanedPreview = stripTrackingParams(url)

  return (
    <Sheet open onClose={onClose} label="链接操作" side="bottom">
      <div className="flex flex-col gap-3 px-4 pb-[max(1rem,var(--safe-bottom))] pt-2" data-n358-sheet="">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium text-[var(--lumi-text-tertiary)]" data-n358-domain="">
              {domain ?? '域名不可用'}
            </p>
            <p className="mt-0.5 break-all text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
              {url}
            </p>
          </div>
          <IconButton size="sm" icon={<X aria-hidden className="size-4" />} label="关闭链接操作" touch onClick={onClose} />
        </div>

        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            data-testid="n358-copy"
            onClick={() => void copy('plain')}
            className="flex min-h-11 items-center justify-center gap-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 text-xs font-medium text-[var(--lumi-text-primary)] hover:bg-[var(--lumi-surface-hover)]"
          >
            {copied === 'plain' ? <Check aria-hidden className="size-4 text-[var(--lumi-success)]" /> : <ClipboardCopy aria-hidden className="size-4" />}
            {copied === 'plain' ? '已复制' : '复制链接'}
          </button>
          <button
            type="button"
            data-testid="n358-copy-clean"
            onClick={() => void copy('clean')}
            className="flex min-h-11 items-center justify-center gap-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 text-xs font-medium text-[var(--lumi-text-primary)] hover:bg-[var(--lumi-surface-hover)]"
          >
            {copied === 'clean' ? <Check aria-hidden className="size-4 text-[var(--lumi-success)]" /> : <Link2Off aria-hidden className="size-4" />}
            {copied === 'clean' ? '已复制净链' : '复制净链接'}
          </button>
          <button
            type="button"
            data-testid="n358-later"
            onClick={toggleLater}
            className="flex min-h-11 items-center justify-center gap-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 text-xs font-medium text-[var(--lumi-text-primary)] hover:bg-[var(--lumi-surface-hover)]"
          >
            <Hourglass aria-hidden className="size-4" />
            {isLater ? '移出稍后打开' : '稍后打开'}
          </button>
          <button
            type="button"
            data-testid="n358-open"
            onClick={() => openLater(url)}
            className="flex min-h-11 items-center justify-center gap-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 text-xs font-medium text-[var(--lumi-text-primary)] hover:bg-[var(--lumi-surface-hover)]"
          >
            <ExternalLink aria-hidden className="size-4" />
            立即打开
          </button>
        </div>

        {cleanedPreview.removed.length > 0 && (
          <p className="text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
            净链接将移除 {cleanedPreview.removed.length} 个跟踪参数
            （{cleanedPreview.removed.join('、')}）。
          </p>
        )}

        {/* 已授权剪藏操作：一次性预填交接（抓取在剪藏页确认后发生） */}
        <button
          type="button"
          data-testid="n358-clip"
          onClick={stageClip}
          className="flex min-h-11 items-center justify-center gap-1.5 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-accent-soft)] px-2 text-xs font-medium text-[var(--lumi-accent-text)] hover:bg-[var(--lumi-accent-soft)]"
        >
          <Scissors aria-hidden className="size-4" />
          送到剪藏（预填确认）
        </button>

        {/* 稍后打开清单（本机；打开动作 = 用户显式点击） */}
        {laterItems.length > 0 && (
          <section aria-label="稍后打开清单" className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
            <h3 className="text-xs font-medium text-[var(--lumi-text-tertiary)]">
              稍后打开（本机 {laterItems.length}）
            </h3>
            <ul className="mt-1 flex max-h-32 flex-col gap-0.5 overflow-y-auto">
              {laterItems.map((item) => (
                <li key={item.url} data-n358-later-item={item.url} className="flex items-center gap-1.5">
                  <span className="min-w-0 flex-1 truncate text-xs text-[var(--lumi-text-secondary)]">
                    {item.domain ?? item.url}
                  </span>
                  <button
                    type="button"
                    aria-label={`立即打开 ${item.domain ?? item.url}`}
                    onClick={() => openLater(item.url)}
                    className="flex min-h-11 items-center rounded-[var(--lumi-radius-sm)] px-1.5 text-xs text-[var(--lumi-accent-text)] hover:bg-[var(--lumi-surface-hover)]"
                  >
                    <ExternalLink aria-hidden className="size-3.5" />
                  </button>
                  <button
                    type="button"
                    aria-label={`移出 ${item.domain ?? item.url}`}
                    onClick={() => {
                      removeLinkLater(item.url)
                      setLaterItems(readLinkLater())
                    }}
                    className="flex min-h-11 items-center rounded-[var(--lumi-radius-sm)] px-1.5 text-xs text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]"
                  >
                    <X aria-hidden className="size-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        <p className="text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
          本面板不发起任何远端预览请求；打开网页或剪藏抓取都发生在你
          显式确认之后。
        </p>
      </div>
    </Sheet>
  )
}

/** 长按手势（事件委托挂正文容器）：跨源 http(s) 外链长按 550ms 弹出
 * 操作面板。移动 >10px / 提前抬起取消；长按后浏览器合成的 click 被
 * 吞掉一次（不导航），正常轻点行为完全不变。 */
export function LinkActionGesture({ containerRef }: { containerRef: React.RefObject<HTMLElement | null> }) {
  const [activeUrl, setActiveUrl] = useState<string | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (container === null) return
    let timer: number | null = null
    let suppressClick: string | null = null

    const resolveAnchor = (target: EventTarget | null): { anchor: Element; url: string } | null => {
      const anchor = (target as HTMLElement | null)?.closest('a[href]')
      if (anchor === null) return null
      const href = anchor.getAttribute('href')
      if (href === null) return null
      try {
        const resolved = new URL(href, document.baseURI).toString()
        if (!isExternalHttpUrl(resolved, document.baseURI)) return null
        return { anchor, url: resolved }
      } catch {
        return null
      }
    }

    const onTouchStart = (event: TouchEvent) => {
      const hit = resolveAnchor(event.target)
      if (hit === null) return
      const touch = event.touches[0]
      const startX = touch?.clientX ?? 0
      const startY = touch?.clientY ?? 0
      const cleanup = () => {
        if (timer !== null) {
          window.clearTimeout(timer)
          timer = null
        }
        hit.anchor.removeEventListener('touchmove', onTouchMove)
        hit.anchor.removeEventListener('touchend', onTouchEnd)
      }
      const onTouchMove = (move: TouchEvent) => {
        const moveTouch = move.touches[0]
        if (
          moveTouch !== undefined &&
          (Math.abs(moveTouch.clientX - startX) > 10 || Math.abs(moveTouch.clientY - startY) > 10)
        ) {
          cleanup()
        }
      }
      const onTouchEnd = () => {
        cleanup()
      }
      timer = window.setTimeout(() => {
        cleanup()
        suppressClick = hit.url
        setActiveUrl(hit.url)
      }, LINK_LONG_PRESS_MS)
      hit.anchor.addEventListener('touchmove', onTouchMove, { passive: true })
      hit.anchor.addEventListener('touchend', onTouchEnd)
    }

    const onClickCapture = (event: MouseEvent) => {
      if (suppressClick === null) return
      const hit = resolveAnchor(event.target)
      if (hit !== null && hit.url === suppressClick) {
        event.preventDefault()
        event.stopPropagation()
        suppressClick = null
      }
    }

    container.addEventListener('touchstart', onTouchStart, { passive: true })
    container.addEventListener('click', onClickCapture, true)
    return () => {
      if (timer !== null) window.clearTimeout(timer)
      container.removeEventListener('touchstart', onTouchStart)
      container.removeEventListener('click', onClickCapture, true)
    }
  }, [containerRef])

  return <LinkActionSheet url={activeUrl} onClose={() => setActiveUrl(null)} />
}

export default LinkActionSheet
