/** SidebarHeader — 侧边栏品牌区（0011 Gate 1，参考图 01-sidebar）。
 *
 * 同一组件用于桌面固定侧栏与移动导航抽屉：LumiRSS + 流光阅源 副标题
 * + 右上角圆形设置图标按钮（SettingsButton，设置入口的唯一位置）。 */

import SettingsButton from './SettingsButton'

export default function SidebarHeader() {
  return (
    <div className="flex items-start justify-between gap-2 px-2.5 pb-1 pt-2">
      <div className="min-w-0">
        <h1 className="text-base font-semibold tracking-tight text-[var(--lumi-text-primary)]">
          LumiRSS
        </h1>
        <p className="text-xs text-[var(--lumi-text-tertiary)]">流光阅源</p>
      </div>
      <div className="mt-0.5">
        <SettingsButton />
      </div>
    </div>
  )
}
