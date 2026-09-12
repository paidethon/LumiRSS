/** SettingsButton — 设置入口按钮（0011 修正补充）。
 *
 * 从 SidebarHeader 抽出：展开态（圆形带边框）与折叠态（纯 icon）
 * 共用同一打开逻辑与响应式设置壳（桌面 Modal / 移动全屏页）——
 * 同一语义位置（Spec AC2）。 */

import { Settings } from 'lucide-react'
import { useEffect, useState } from 'react'
import SettingsShell from './SettingsShell'
import {
  onCloseSettingsRequest,
  onOpenSettingsRequest,
  type SettingsOpenDetail,
} from './settings/settings-bridge'
import { cx } from './ui/cx'

export default function SettingsButton({ collapsed }: { collapsed?: boolean }) {
  const [open, setOpen] = useState(false)
  // P0-12：主界面导航的深链请求（打开设置并直达分类）；null = 无深链。
  const [deepLink, setDeepLink] = useState<SettingsOpenDetail | null>(null)

  // 设置页内容可请求关闭设置壳（跳转订阅中心等主界面动作）
  useEffect(() => onCloseSettingsRequest(() => setOpen(false)), [])
  // 主界面（侧栏「API 来源」「邮件简报」等）可请求打开设置并直达分类
  useEffect(
    () =>
      onOpenSettingsRequest((detail) => {
        setDeepLink(detail)
        setOpen(true)
      }),
    [],
  )

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="打开设置"
        title="设置"
        className={cx(
          'flex shrink-0 items-center justify-center rounded-full text-[var(--lumi-text-secondary)]',
          'transition-colors duration-[var(--lumi-motion-fast)]',
          'hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
          'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
          collapsed
            ? 'size-10 text-[var(--lumi-text-secondary)]'
            : 'size-9 border border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
        )}
      >
        <Settings aria-hidden className="size-4" />
      </button>

      {/* 响应式设置壳：桌面 Modal / 移动全屏页。两者都 portal 到 body
       * （Base UI），CSS 无法再切换挂载——按断点 JS 择一渲染，避免
       * 隐藏壳与可见壳争抢焦点/滚动锁。P0-12：深链分类随请求透传。 */}
      <SettingsShell
        open={open}
        onClose={() => setOpen(false)}
        openCategory={deepLink}
      />
    </>
  )
}
