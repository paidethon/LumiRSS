/** SettingsShell — 设置入口的懒加载响应式壳（Phase K bundle 分割）。
 *
 * 设置子树（13 个分类页 + 备份/恢复 + RSSHub 控制中心 + AI 配置，
 * ~4000 行）只在第一次真正打开设置时才加载对应 chunk：
 * React.lazy 只有在组件被渲染时才发起 dynamic import，因此这里用
 * ``open`` 门控——关闭状态连 chunk 请求都不发。桌面 Modal 与移动
 * 全屏页各自独立 chunk（移动端只拉移动壳）。
 *
 * 加载期间显示轻量占位（不阻塞交互，chunk 在局域网/缓存下亚秒）。
 */

import { lazy, Suspense } from 'react'
import { Loader2 } from 'lucide-react'
import { useIsMobile } from '../lib/use-is-mobile'

const SettingsModal = lazy(() => import('./settings/SettingsModal'))
const MobileSettingsScreen = lazy(() => import('./MobileSettingsScreen'))

function SettingsLoading() {
  return (
    <div className="flex min-h-40 items-center justify-center" role="status" aria-label="设置加载中">
      <Loader2 aria-hidden className="size-5 animate-spin text-[var(--lumi-text-tertiary)]" />
    </div>
  )
}

export default function SettingsShell({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const isMobile = useIsMobile()
  if (!open) return null
  return (
    <Suspense fallback={<SettingsLoading />}>
      {isMobile ? (
        <MobileSettingsScreen open={open} onClose={onClose} />
      ) : (
        <SettingsModal open={open} onClose={onClose} />
      )}
    </Suspense>
  )
}
