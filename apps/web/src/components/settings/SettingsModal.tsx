/** SettingsModal — 桌面设置中心外壳（0010 Gate A / 0010a Gate E 重构）。
 *
 * 分类内容与定义在 categories.tsx（E1 共享模块）——移动端
 * MobileSettingsScreen 与本组件消费同一组分类页与同一 store。
 *
 * 结构对照 Folo 实测（UPSTREAMS.md §Settings modal measurements）：
 * - Modal ~950×800（min(880px, 84vw) × min(72vh, 640px)）、圆角 12px；
 * - 左导航 ~176px：lucide 图标 + 标签，行 34px / r8 / 选中 selected surface
 *   + accent；导航条目多时导航区自身滚动（Folo 同款）；
 * - 右内容：独立滚动区，由 SettingItemList 声明式渲染。
 *
 * 关闭路径（AC3）：点空白遮罩 / Escape / ✕——全部由 Dialog primitive 提供。
 * <768px 不渲染本组件（由 MobileSettingsScreen 接管）。 */

import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { Dialog } from '../ui/Dialog'
import { Button } from '../ui/Button'
import { IconButton } from '../ui/IconButton'
import { SettingItemList } from './SettingItem'
import { useHasDirtySettings } from './settings-dirty'
import {
  CATEGORIES,
  categoryLabel,
  toCategoryId,
  useCategoryItems,
  type CategoryId,
} from './categories'
import type { SettingsOpenDetail } from './settings-bridge'
import { cx } from '../ui/cx'
import { ReadingPreviewPane } from './reader/ReadingPreviewPane'

/** FIX-057：被脏状态拦截、等待用户决策的导航意图。 */
type PendingNav = { kind: 'category'; id: CategoryId } | { kind: 'close' } | null

export default function SettingsModal({
  open,
  onClose,
  openCategory,
}: {
  open: boolean
  onClose: () => void
  /** P0-12：主界面导航深链（直达分类）；未知 id 安全降级为通用分类。 */
  openCategory?: SettingsOpenDetail | null
}) {
  const [category, setCategory] = useState<CategoryId>('general')
  const items = useCategoryItems(category)
  // FIX-057：任一表单分区登记了未保存更改 → 切分类 / 关闭前先确认。
  const hasDirty = useHasDirtySettings()
  const [pendingNav, setPendingNav] = useState<PendingNav>(null)

  const requestNavigate = (id: CategoryId): void => {
    if (id === category) return
    if (hasDirty) setPendingNav({ kind: 'category', id })
    else setCategory(id)
  }
  const requestClose = (): void => {
    if (hasDirty) setPendingNav({ kind: 'close' })
    else onClose()
  }
  const confirmPendingNav = (): void => {
    if (pendingNav === null) return
    if (pendingNav.kind === 'category') setCategory(pendingNav.id)
    else onClose()
    setPendingNav(null)
  }

  // 深链请求（每次请求 seq 递增 → 对象身份变化即应用；同一分类重复
  // 请求同样生效）。未知 id 由 toCategoryId 安全降级为通用分类。
  useEffect(() => {
    if (openCategory !== null && openCategory !== undefined && openCategory.category) {
      setCategory(toCategoryId(openCategory.category))
    }
  }, [openCategory])

  return (
    <Dialog open={open} onClose={requestClose} title="设置" panelClassName="!max-w-none w-auto p-0" hideTitle>
      {/* 自定义头部（Dialog 内置标题已隐藏；此 h2 即对话框的可访问名字） */}
      <div className="flex items-center justify-between border-b border-[var(--lumi-separator)] px-5 py-3.5">
        <h2 className="text-base font-semibold text-[var(--lumi-text-primary)]">设置</h2>
        <IconButton icon={<X aria-hidden className="size-4" />} label="关闭设置" onClick={requestClose} />
      </div>
      {/* fresh-eyes Issue 7：上限叠加 Dialog 的 85dvh 减去自带头部，
          矮窗口下头部（含关闭按钮）不再被滚出可视区。 */}
      <div className="flex h-[min(72vh,640px)] max-h-[calc(85dvh-3.5rem)] w-[min(880px,84vw)]">
        {/* 左导航（Folo 实测：行 34px / r8 / 选中 selected surface）。
            13 分类高度可能超出 → 导航区自身滚动。 */}
        <nav
          aria-label="设置分类"
          className="flex w-44 shrink-0 flex-col gap-0.5 overflow-y-auto border-r border-[var(--lumi-separator)] pr-2.5"
        >
          {CATEGORIES.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => requestNavigate(c.id)}
              aria-current={category === c.id ? 'true' : undefined}
              className={cx(
                'flex items-center gap-2.5 rounded-[var(--lumi-radius-md)] px-2.5 py-1.5 text-left text-sm',
                'min-h-[34px] transition-colors duration-[var(--lumi-motion-fast)]',
                'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                category === c.id
                  ? 'bg-[var(--lumi-surface-selected)] font-medium text-[var(--lumi-accent-text)]'
                  : 'text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
              )}
            >
              {c.icon}
              {c.label}
            </button>
          ))}
        </nav>

        {/* 右内容（Folo 实测：px-32 等效、独立滚动）。
            P14：阅读分类 side-by-side 实时预览——左列表 + 右预览栏；
            其余分类维持单列。预览栏 ≥lg 视口出现（窄 Modal 不挤占列表）。 */}
        <div className="min-w-0 flex-1 pl-6">
          <h2 className="mb-2 text-base font-semibold text-[var(--lumi-text-primary)]">
            {categoryLabel(category)}
          </h2>
          {category === 'reading' ? (
            <div className="flex h-[calc(100%-2rem)] min-h-0 gap-4">
              <div className="min-w-0 flex-1 overflow-y-auto pr-1">
                <SettingItemList items={items} />
              </div>
              <aside
                aria-label="阅读样式实时预览"
                className="hidden w-72 shrink-0 overflow-y-auto lg:block"
              >
                <ReadingPreviewPane />
              </aside>
            </div>
          ) : (
            <div className="h-[calc(100%-2rem)] overflow-y-auto pr-1">
              <SettingItemList items={items} />
            </div>
          )}
        </div>
      </div>

      {/* FIX-057：未保存更改的统一离场确认（Escape/遮罩由 Dialog 承担；
          保存动作在各自分区——此处只提供 放弃 / 留下 两个选项）。 */}
      <Dialog
        open={pendingNav !== null}
        onClose={() => setPendingNav(null)}
        title="有未保存的更改"
        footer={
          <>
            <Button variant="ghost" onClick={() => setPendingNav(null)}>
              继续编辑
            </Button>
            <Button variant="danger" onClick={confirmPendingNav}>
              放弃并离开
            </Button>
          </>
        }
      >
        <p className="text-sm leading-relaxed text-[var(--lumi-text-primary)]">
          当前分区有未保存的更改。离开将丢弃这些更改；要保留请先在分区内保存。
        </p>
      </Dialog>
    </Dialog>
  )
}
