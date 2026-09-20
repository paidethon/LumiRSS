/** ArticleLinksPanel — F054 文中链接面板。
 *
 * ArticleContent 净化后 DOM 上收集 a[href]（lib/collect-article-links）：
 * 按域名分组、显示链接文字+目标（可复制）、「定位」滚动到原文该元素并
 * 短暂高亮、「打开」仅 http/https。危险协议（javascript:/data:/vbscript:）
 * 在收集层即被排除——不出现、不可执行。
 */

import { useMemo, useRef, useState } from 'react'
import { Check, Copy, Crosshair, X } from 'lucide-react'
import { collectArticleLinks, displayUrl, groupLinksByHost } from '../lib/collect-article-links'
import { safeExternalHttpUrl } from '../lib/safe-external-http-url'
import { Button } from './ui/Button'
import { EmptyState } from './ui/EmptyState'

export default function ArticleLinksPanel({
  containerRef,
  onClose,
}: {
  containerRef: React.RefObject<HTMLElement | null>
  onClose: () => void
}) {
  const [copied, setCopied] = useState<string | null>(null)
  const copyTimer = useRef<number | undefined>(undefined)
  const links = useMemo(() => {
    const container = containerRef.current
    if (container === null) return []
    return collectArticleLinks(container)
  }, [containerRef])
  const groups = useMemo(() => groupLinksByHost(links), [links])

  const copy = (url: string) => {
    void navigator.clipboard?.writeText(url).then(() => {
      setCopied(url)
      window.clearTimeout(copyTimer.current)
      copyTimer.current = window.setTimeout(() => setCopied(null), 1500)
    })
  }

  const locate = (href: string) => {
    const container = containerRef.current
    if (container === null) return
    const anchors = container.querySelectorAll<HTMLAnchorElement>('a[href]')
    for (const anchor of anchors) {
      try {
        const resolved = new URL(anchor.getAttribute('href') ?? '', document.baseURI).toString()
        if (resolved === href) {
          anchor.scrollIntoView({ block: 'center' })
          anchor.classList.add('lumi-link-flash')
          window.setTimeout(() => anchor.classList.remove('lumi-link-flash'), 1500)
          anchor.focus()
          return
        }
      } catch {
        continue
      }
    }
  }

  return (
    <div
      role="dialog"
      aria-label="文中链接"
      className="absolute right-4 top-16 z-30 max-h-[70vh] w-[min(24rem,calc(100vw-2rem))] overflow-y-auto rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] p-3 shadow-lg"
    >
      <div className="mb-2 flex items-center gap-2">
        <p className="flex-1 text-xs font-medium text-[var(--lumi-text-primary)]">
          文中链接（{links.length}）
        </p>
        <Button size="sm" variant="ghost" onClick={onClose} aria-label="关闭文中链接面板">
          <X aria-hidden className="size-3.5" />
        </Button>
      </div>
      {links.length === 0 && <EmptyState title="本文没有外链" description="文章净化后未收集到任何链接。" />}
      {[...groups.entries()].map(([host, hostLinks]) => (
        <section key={host} className="mb-3">
          <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-[var(--lumi-text-tertiary)]">
            {host}（{hostLinks.length}）
          </p>
          <ul className="flex flex-col gap-1">
            {hostLinks.map((link) => {
              const safe = safeExternalHttpUrl(link.href)
              return (
                <li key={link.href} className="rounded-[var(--lumi-radius-md)] px-2 py-1.5 text-xs hover:bg-[var(--lumi-surface-hover)]">
                  <p className="truncate text-[var(--lumi-text-primary)]">{link.text}</p>
                  <p className="flex items-center gap-1.5 text-[var(--lumi-text-tertiary)]">
                    <span className="min-w-0 flex-1 truncate font-mono">{displayUrl(link.href)}</span>
                    <button
                      type="button"
                      aria-label="复制链接"
                      onClick={() => copy(link.href)}
                      className="text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-text-primary)]"
                    >
                      {copied === link.href ? <Check aria-hidden className="size-3.5" /> : <Copy aria-hidden className="size-3.5" />}
                    </button>
                    <button
                      type="button"
                      aria-label="定位到原文"
                      onClick={() => locate(link.href)}
                      className="text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-text-primary)]"
                    >
                      <Crosshair aria-hidden className="size-3.5" />
                    </button>
                    {safe !== null && (
                      <a
                        href={safe}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="text-[var(--lumi-accent)] hover:underline"
                        aria-label="打开链接"
                      >
                        打开
                      </a>
                    )}
                  </p>
                </li>
              )
            })}
          </ul>
        </section>
      ))}
    </div>
  )
}
