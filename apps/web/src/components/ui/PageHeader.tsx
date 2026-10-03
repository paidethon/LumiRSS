/** PageHeader primitive — R3 共享契约 §2（Wave0 foundation）。
 *
 * 页面头部：标题区（title + 可选 subtitle）+ 操作区（actions）+ 可选
 * 返回位（back）。移动/桌面同构——同一 DOM，靠 truncate 与 flex 换行
 * 适应窄屏，不渲染两套响应式壳（portal 壳才需要 JS 分派）。
 *
 * 语义：标题默认 h1；嵌入已持有 h1 的页面时用 headingLevel="h2" 降级，
 * 避免一页多 h1。返回位是受控数据（label + onClick）而非任意节点——
 * 保证返回按钮永远带 ArrowLeft 图标与可访问名称；其他头部控件走
 * actions 插槽（Button / IconButton / ActionMenu 均可）。 */

import { ArrowLeft } from 'lucide-react'
import type { ReactNode } from 'react'
import { Button } from './Button'
import { cx } from './cx'

export interface PageHeaderBack {
  /** 返回按钮文案（可访问名称） */
  label: string
  onClick: () => void
}

export interface PageHeaderProps {
  title: ReactNode
  subtitle?: ReactNode
  /** 操作区（按钮等），渲染在标题右侧 */
  actions?: ReactNode
  /** 返回位：传入即渲染带箭头的返回按钮 */
  back?: PageHeaderBack
  /** 标题语义层级（默认 h1；页面已有 h1 时传 h2） */
  headingLevel?: 'h1' | 'h2'
  className?: string
}

export function PageHeader({
  title,
  subtitle,
  actions,
  back,
  headingLevel = 'h1',
  className,
}: PageHeaderProps) {
  const Heading = headingLevel
  return (
    <header className={cx('flex min-w-0 flex-col gap-1', className)}>
      <div className="flex min-w-0 items-center gap-1.5">
        {back && (
          <Button
            variant="ghost"
            size="sm"
            onClick={back.onClick}
            className="max-lg:min-h-11 shrink-0 pl-1.5"
          >
            <ArrowLeft aria-hidden="true" className="size-4 shrink-0" />
            {back.label}
          </Button>
        )}
        <div className="min-w-0 flex-1">
          <Heading className="truncate text-base font-semibold leading-tight text-[var(--lumi-text-primary)]">
            {title}
          </Heading>
          {subtitle !== undefined && (
            <p className="mt-0.5 truncate text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
              {subtitle}
            </p>
          )}
        </div>
        {actions !== undefined && (
          <div className="flex shrink-0 items-center gap-1.5">{actions}</div>
        )}
      </div>
    </header>
  )
}
