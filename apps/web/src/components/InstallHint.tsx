/** InstallHint — 克制的「添加到主屏幕」引导（Phase M）。
 *
 * 原则（spec：不要每次弹）：
 * - 已经在 standalone（含 iOS navigator.standalone）→ 永不出现；
 * - 用户点关闭 → localStorage 记 dismissed，永不再弹（非敏感 UI 偏好，
 *   允许 localStorage）；
 * - Android Chrome：等 beforeinstallprompt 真实可用才显示，点击直接
 *   唤起系统安装弹窗；安装完成（appinstalled）记录 installed；
 * - iOS Safari：无 beforeinstallprompt，显示一次「分享 → 添加到主屏幕」
 *   的文字指引（含图标释义），不伪造安装按钮。
 * - 仅移动端视口渲染；桌面浏览器不叨扰。
 */

import { useEffect, useState } from 'react'
import { Share, Smartphone, X } from 'lucide-react'
import { useIsMobile } from '../lib/use-is-mobile'

const DISMISS_KEY = 'lumirss-install-hint'

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

function isStandalone(): boolean {
  if (typeof window.matchMedia === 'function') {
    if (window.matchMedia('(display-mode: standalone)').matches) return true
  }
  const nav = navigator as Navigator & { standalone?: boolean }
  return nav.standalone === true
}

function isIOS(): boolean {
  // iOS Safari（含旧式 iPad UA）；iOS 不会触发 beforeinstallprompt。
  return /iphone|ipad|ipod/i.test(navigator.userAgent)
}

export default function InstallHint() {
  const isMobile = useIsMobile()
  const [visible, setVisible] = useState(false)
  const [promptEvent, setPromptEvent] = useState<BeforeInstallPromptEvent | null>(null)
  const [showIOSSteps, setShowIOSSteps] = useState(false)

  useEffect(() => {
    if (!isMobile || isStandalone()) return
    if (localStorage.getItem(DISMISS_KEY) === 'dismissed') return

    if (isIOS()) {
      // 等 3s 再出现：不打断首屏阅读，确认用户真的停留。
      const timer = window.setTimeout(() => setVisible(true), 3000)
      return () => window.clearTimeout(timer)
    }
    const onBeforeInstall = (event: Event) => {
      event.preventDefault()
      setPromptEvent(event as BeforeInstallPromptEvent)
      setVisible(true)
    }
    const onInstalled = () => {
      localStorage.setItem(DISMISS_KEY, 'installed')
      setVisible(false)
    }
    window.addEventListener('beforeinstallprompt', onBeforeInstall)
    window.addEventListener('appinstalled', onInstalled)
    return () => {
      window.removeEventListener('beforeinstallprompt', onBeforeInstall)
      window.removeEventListener('appinstalled', onInstalled)
    }
  }, [isMobile])

  if (!isMobile || !visible) return null

  function dismiss() {
    localStorage.setItem(DISMISS_KEY, 'dismissed')
    setVisible(false)
  }

  async function install() {
    if (!promptEvent) {
      setShowIOSSteps(true)
      return
    }
    await promptEvent.prompt()
    const choice = await promptEvent.userChoice
    if (choice.outcome === 'accepted') {
      localStorage.setItem(DISMISS_KEY, 'installed')
      setVisible(false)
    }
  }

  return (
    <div
      role="complementary"
      aria-label="安装引导"
      className="fixed inset-x-3 bottom-[calc(var(--safe-bottom)+4.5rem)] z-[var(--lumi-z-floating)] rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] p-3.5 shadow-[var(--lumi-shadow-floating)] lg:hidden"
    >
      <div className="flex items-start gap-3">
        <Smartphone aria-hidden className="mt-0.5 size-5 shrink-0 text-[var(--lumi-accent-text)]" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-[var(--lumi-text-primary)]">
            把 LumiRSS 装到主屏幕
          </p>
          {showIOSSteps || (!promptEvent && isIOS()) ? (
            <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
              点 Safari 底部的
              <Share aria-hidden className="mx-0.5 inline size-3.5 align-[-2px]" />
              「分享」→「添加到主屏幕」，即可全屏使用、像 App 一样启动。
            </p>
          ) : (
            <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
              全屏使用、像 App 一样启动，无需应用商店。
            </p>
          )}
          <div className="mt-2.5 flex gap-2">
            <button
              type="button"
              onClick={install}
              className="min-h-9 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-accent)] px-3 text-sm font-medium text-[var(--lumi-accent-contrast)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-accent-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
            >
              安装
            </button>
            <button
              type="button"
              onClick={dismiss}
              className="min-h-9 rounded-[var(--lumi-radius-md)] px-3 text-sm text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
            >
              不用了
            </button>
          </div>
        </div>
        <button
          type="button"
          onClick={dismiss}
          aria-label="关闭安装引导"
          className="flex size-8 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        >
          <X aria-hidden className="size-4" />
        </button>
      </div>
    </div>
  )
}
