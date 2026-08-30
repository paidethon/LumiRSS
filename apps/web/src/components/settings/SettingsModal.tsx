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

import { useState } from 'react'
import { Dialog } from '../ui/Dialog'
import { SettingItemList } from './SettingItem'
import { CATEGORIES, categoryLabel, useCategoryItems, type CategoryId } from './categories'
import { cx } from '../ui/cx'

export default function SettingsModal({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const [category, setCategory] = useState<CategoryId>('general')
  const items = useCategoryItems(category)

  return (
    <Dialog open={open} onClose={onClose} title="设置" panelClassName="!max-w-none w-auto p-0" hideTitle>
      {/* 自定义头部（Dialog 内置标题已隐藏；此 h2 即对话框的可访问名字） */}
      <div className="flex items-center justify-between border-b border-[var(--lumi-separator)] px-5 py-3.5">
        <h2 className="text-base font-semibold text-[var(--lumi-text-primary)]">设置</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="关闭设置"
          className="flex size-8 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        >
          <svg aria-hidden="true" width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M1 1L13 13M13 1L1 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
      </div>
      <div className="flex h-[min(72vh,640px)] w-[min(880px,84vw)]">
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
              onClick={() => setCategory(c.id)}
              aria-current={category === c.id ? 'true' : undefined}
              className={cx(
                'flex items-center gap-2.5 rounded-[var(--lumi-radius-md)] px-2.5 py-1.5 text-left text-sm',
                'min-h-[34px] transition-colors duration-[var(--lumi-motion-fast)]',
                'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                category === c.id
                  ? 'bg-[var(--lumi-surface-selected)] font-medium text-[var(--lumi-accent)]'
                  : 'text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
              )}
            >
              {c.icon}
              {c.label}
            </button>
          ))}
        </nav>

        {/* 右内容（Folo 实测：px-32 等效、独立滚动） */}
        <div className="min-w-0 flex-1 pl-6">
          <h2 className="mb-2 text-base font-semibold text-[var(--lumi-text-primary)]">
            {categoryLabel(category)}
          </h2>
          <div className="h-[calc(100%-2rem)] overflow-y-auto pr-1">
            <SettingItemList items={items} />
          </div>
        </div>
      </div>
    </Dialog>
  )
}
