/** AddSourceDialog — 0014 统一「添加来源」对话框（三模式单表面）。
 *
 * 取代 0013 的 AddSubscriptionDialog（直接 RSS/Atom 逻辑原样迁移到
 * DirectFeedTab），并新增 0014 的网站发现与 RSSHub 两种模式：
 *
 *   RSS / Atom 地址  → 直接预览（0013 管道，行为不变）
 *   网站地址         → POST /api/v1/source-discovery → 候选 → 预览 → 订阅
 *   RSSHub           → 路由目录 → 参数表单 → 预览 → 订阅
 *
 * 三种模式共用 PreviewStage（预览 metadata → 分类 → POST /subscriptions
 * → invalidate），不重复订阅逻辑、不建第二套管理入口。
 *
 * a11y：tablist 键盘导航（←/→）、aria-selected、44px 触控目标、
 * Escape/遮罩关闭受各 tab 的 busy 防护（提交中不允许误关）。 */

import { useCallback, useRef, useState } from 'react'
import { Dialog } from './ui/Dialog'
import { cx } from './ui/cx'
import { DirectFeedTab } from './add-source/DirectFeedTab'
import { WebsiteTab } from './add-source/WebsiteTab'
import { RssHubTab } from './add-source/RssHubTab'

type SourceTab = 'rss' | 'website' | 'rsshub'

const TABS: { id: SourceTab; label: string }[] = [
  { id: 'rss', label: 'RSS / Atom' },
  { id: 'website', label: '网站' },
  { id: 'rsshub', label: 'RSSHub' },
]

export default function AddSourceDialog({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const [tab, setTab] = useState<SourceTab>('rss')

  // 当前 tab 注册的关闭防护（busy 时拒绝关闭）
  const guardRef = useRef<(() => void) | null>(null)
  const registerGuard = useCallback((fn: (() => void) | null) => {
    guardRef.current = fn
  }, [])

  const close = useCallback(() => {
    if (guardRef.current !== null) guardRef.current()
    else onClose()
    // 关闭时复位模式与防护（下次打开从 RSS/Atom 开始）
    setTab('rss')
    guardRef.current = null
  }, [onClose])

  function onTabKeyDown(event: React.KeyboardEvent, current: SourceTab) {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    const index = TABS.findIndex((t) => t.id === current)
    const next =
      event.key === 'ArrowRight'
        ? (index + 1) % TABS.length
        : (index - 1 + TABS.length) % TABS.length
    setTab(TABS[next].id)
    document.getElementById(`add-source-tab-${TABS[next].id}`)?.focus()
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      title="添加来源"
      fullscreenOnMobile
      panelClassName="max-w-lg"
    >
      {/* 模式切换（tablist：←/→ 键盘导航 + aria-selected） */}
      <div
        role="tablist"
        aria-label="来源类型"
        className="mb-4 flex gap-1 rounded-[var(--lumi-radius-lg)] bg-[var(--lumi-surface)] p-1"
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            id={`add-source-tab-${t.id}`}
            role="tab"
            type="button"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            onKeyDown={(e) => onTabKeyDown(e, t.id)}
            className={cx(
              'min-h-11 flex-1 rounded-[var(--lumi-radius-md)] px-2 py-2 text-xs font-medium',
              'transition-colors duration-[var(--lumi-motion-fast)]',
              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
              tab === t.id
                ? 'bg-[var(--lumi-surface-elevated)] text-[var(--lumi-text-primary)] shadow-[var(--lumi-shadow-sm)]'
                : 'text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)]',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div
        role="tabpanel"
        aria-labelledby={`add-source-tab-${tab}`}
        className="flex flex-col"
      >
        {tab === 'rss' && (
          <DirectFeedTab onClose={onClose} registerGuard={registerGuard} />
        )}
        {tab === 'website' && (
          <WebsiteTab onClose={onClose} registerGuard={registerGuard} />
        )}
        {tab === 'rsshub' && (
          <RssHubTab onClose={onClose} registerGuard={registerGuard} />
        )}
      </div>
    </Dialog>
  )
}
