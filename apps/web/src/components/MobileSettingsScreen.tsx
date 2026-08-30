/** MobileSettingsScreen — 移动端设置（0010a Gate E，<768px）。
 *
 * 结构对照 Folo mobile（apps/mobile modules/settings，inspired）：
 * - 全屏页面（非 Modal）：底部 Tab 设置入口挂载；
 * - 首页 = iOS 风格分组列表（GroupedInsetList：彩色圆角图标 + 标题 +
 *   chevron），分组来自 CATEGORY_GROUPS；
 * - 点击任一行 → push 全屏子页（内部状态栈，无路由依赖）：左上返回
 *   按钮 + 吸顶标题 + 该分类设置项（与桌面共享 useCategoryItems）。
 *
 * 修复背景（AC1/AC2）：0010 Gate D 的「Dialog fullscreenOnMobile + chip
 * 横条」方案在 390px 实测布局损坏（容器缺 max-md:flex-col，内容区被
 * 挤出视口、chips 被 stretch 拉成竖条）——按 Folo 移动端模式重设计。 */

import { useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { CATEGORIES, CATEGORY_GROUPS, categoryLabel, useCategoryItems, type CategoryId } from './settings/categories'
import { SettingItemList } from './settings/SettingItem'
import { cx } from './ui/cx'

export default function MobileSettingsScreen({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  // null = 首页（分组列表）；非 null = 当前 push 的子页分类
  const [page, setPage] = useState<CategoryId | null>(null)

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[var(--lumi-z-dialog)] flex flex-col bg-[var(--lumi-canvas)] md:hidden"
      role="dialog"
      aria-modal="true"
      aria-label="设置"
    >
      {page === null ? (
        /* ---- 首页：分组列表（Folo mobile SettingsList 模式） ---- */
        <>
          <header className="flex items-center justify-between border-b border-[var(--lumi-separator)] bg-[var(--lumi-surface)] px-4 py-3.5">
            <h2 className="text-base font-semibold text-[var(--lumi-text-primary)]">设置</h2>
            <button
              type="button"
              onClick={onClose}
              aria-label="关闭设置"
              className="flex size-11 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
            >
              <svg aria-hidden="true" width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path d="M1 1L13 13M13 1L1 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </button>
          </header>
          <div className="flex-1 overflow-y-auto px-4 py-4">
            {CATEGORY_GROUPS.map((group) => (
              <section key={group.label} className="mb-5">
                <h3 className="mb-1.5 px-1 text-xs font-medium uppercase tracking-wide text-[var(--lumi-text-tertiary)]">
                  {group.label}
                </h3>
                <ul className="divide-y divide-[var(--lumi-separator)] overflow-hidden rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]">
                  {group.ids.map((id) => {
                    const c = CATEGORIES.find((x) => x.id === id)!
                    return (
                      <li key={id}>
                        <button
                          type="button"
                          onClick={() => setPage(id)}
                          className="flex min-h-11 w-full items-center gap-3 px-4 py-2.5 text-left transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                        >
                          <span
                            aria-hidden
                            className="flex size-8 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-selected)] text-[var(--lumi-accent)]"
                          >
                            {c.icon}
                          </span>
                          <span className="flex-1 text-sm text-[var(--lumi-text-primary)]">{c.label}</span>
                          <ChevronRight aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />
                        </button>
                      </li>
                    )
                  })}
                </ul>
              </section>
            ))}
          </div>
        </>
      ) : (
        /* ---- 子页：push 全屏分类页（Folo mobile routes/<Category> 模式） ---- */
        <SubPage id={page} onBack={() => setPage(null)} />
      )}
    </div>
  )
}

function SubPage({ id, onBack }: { id: CategoryId; onBack: () => void }) {
  const items = useCategoryItems(id)
  return (
    <>
      <header className="sticky top-0 flex items-center gap-2 border-b border-[var(--lumi-separator)] bg-[var(--lumi-surface)] px-2 py-2.5">
        <button
          type="button"
          onClick={onBack}
          aria-label="返回设置"
          className={cx(
            'flex size-11 items-center justify-center rounded-[var(--lumi-radius-md)]',
            'text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)]',
            'hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
            'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
          )}
        >
          <ChevronLeft aria-hidden className="size-5" />
        </button>
        <h2 className="text-base font-semibold text-[var(--lumi-text-primary)]">{categoryLabel(id)}</h2>
      </header>
      <div className="flex-1 overflow-y-auto px-4 py-3">
        <SettingItemList items={items} />
      </div>
    </>
  )
}
