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
import { Tabs } from './ui/Tabs'
import { DirectFeedTab } from './add-source/DirectFeedTab'
import { WebsiteTab } from './add-source/WebsiteTab'
import { RssHubTab } from './add-source/RssHubTab'

type SourceTab = 'rss' | 'website' | 'rsshub'

const TABS: { value: SourceTab; label: string }[] = [
  { value: 'rss', label: 'RSS / Atom' },
  { value: 'website', label: '网站' },
  { value: 'rsshub', label: 'RSSHub' },
]

export default function AddSourceDialog({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const [tab, setTab] = useState<SourceTab>('rss')

  // 当前 tab 注册的关闭防护：返回 false = busy，拒绝关闭
  const guardRef = useRef<(() => boolean) | null>(null)
  const registerGuard = useCallback((fn: (() => boolean) | null) => {
    guardRef.current = fn
  }, [])

  const close = useCallback(() => {
    if (guardRef.current !== null && !guardRef.current()) return
    guardRef.current = null
    setTab('rss') // 关闭后复位模式（下次打开从 RSS/Atom 开始）
    onClose()
  }, [onClose])

  return (
    <Dialog
      open={open}
      onClose={close}
      title="添加来源"
      fullscreenOnMobile
      panelClassName="max-w-lg"
    >
      {/* 模式切换（Base UI Tabs：tablist 语义 + ←/→ 键盘导航） */}
      <Tabs<SourceTab>
        aria-label="来源类型"
        value={tab}
        onValueChange={setTab}
        options={TABS}
        panels={{
          rss: <DirectFeedTab onClose={close} registerGuard={registerGuard} />,
          website: <WebsiteTab onClose={close} registerGuard={registerGuard} />,
          rsshub: <RssHubTab onClose={close} registerGuard={registerGuard} />,
        }}
      />
    </Dialog>
  )
}
