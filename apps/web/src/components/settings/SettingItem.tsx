/** SettingItem — 声明式设置行渲染器（0010 Gate A）。
 *
 * 借鉴 Folo setting-builder 的声明式模式（inspired，独立实现）：
 * 一份设置描述数组渲染整个分类页，四型条目：
 *
 *   { type: 'title', value }          → 分组标题（13px/700/半透明，Folo 实测）
 *   { key, label, description? }      → 按值类型自动映射控件：
 *                                        boolean → Switch / 枚举 → Select
 *   { label, description, action, buttonText } → 操作行（按钮在右）
 *   { type: 'custom', node }          → 逃生舱（任意 ReactNode，如快捷键表）
 *
 * 行布局按 Folo 实测（UPSTREAMS.md §Settings modal measurements）：
 * flex justify-between、label 14px/500 居左 + 控件居右、行 mt-16px。
 * 禁用行（planned）保持渲染但控件 disabled。 */

import type { ReactNode } from 'react'
import { Select, type SelectOption } from '../ui/Select'
import { Switch } from '../ui/Switch'
import { Button } from '../ui/Button'
import { cx } from '../ui/cx'

// ---- 类型 ----

export type SettingRowBase = {
  label: string
  description?: string
  /** planned 行：控件禁用 + planned 徽标（诚实原则） */
  planned?: boolean
  /** 归属里程碑（planned 行展示，如 "0011"） */
  plannedFor?: string
  /** 实验性行（0010a）：控件真实可用 + 实验徽标 + 正式版归属 */
  experimental?: boolean
  /** 正式版归属里程碑（实验性行展示，如 "0016"） */
  experimentalFor?: string
}

export type TitleRow = {
  type: 'title'
  value: string
}

export type ToggleRow = SettingRowBase & {
  type: 'toggle'
  checked: boolean
  onCheckedChange: (checked: boolean) => void
}

export type SelectRow<T extends string | number> = SettingRowBase & {
  type: 'select'
  value: T
  options: readonly { value: T; label: string }[]
  onChange: (value: T) => void
}

export type ActionRow = SettingRowBase & {
  type: 'action'
  action: () => void
  buttonText: string
  danger?: boolean
}

export type CustomRow = {
  type: 'custom'
  node: ReactNode
}

export type SettingItemDef =
  | TitleRow
  | ToggleRow
  | SelectRow<string | number>
  | ActionRow
  | CustomRow

// ---- 渲染 ----

function PlannedBadge({ for_ }: { for_?: string }) {
  return (
    <span className="ml-auto shrink-0 self-center rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-2 py-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">
      {for_ ? `planned · ${for_}` : 'planned'}
    </span>
  )
}

function ExperimentalBadge({ for_ }: { for_?: string }) {
  return (
    <span className="ml-auto shrink-0 self-center rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-2 py-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">
      {for_ ? `实验性 · 正式版 ${for_}` : '实验性'}
    </span>
  )
}

function RowShell({
  label,
  description,
  planned,
  plannedFor,
  experimental,
  experimentalFor,
  children,
}: SettingRowBase & { children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-3">
      <div className="min-w-0">
        <label className="text-sm font-medium leading-none text-[var(--lumi-text-primary)]">
          {label}
        </label>
        {description !== undefined && (
          <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
            {description}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2.5">
        {children}
        {planned && <PlannedBadge for_={plannedFor} />}
        {!planned && experimental && <ExperimentalBadge for_={experimentalFor} />}
      </div>
    </div>
  )
}

function toSelectOptions(options: readonly { value: string | number; label: string }[]): SelectOption[] {
  return options.map((o) => ({ value: String(o.value), label: o.label }))
}

/** 单条渲染（Folo builder 的最小对照实现）。 */
export function SettingItem({ def }: { def: SettingItemDef }) {
  switch (def.type) {
    case 'title':
      return (
        <h3 className="mt-8 px-0.5 text-[13px] font-bold text-[var(--lumi-text-tertiary)] first:mt-0">
          {def.value}
        </h3>
      )
    case 'toggle':
      return (
        <RowShell {...def}>
          <Switch
            checked={def.checked}
            onCheckedChange={def.onCheckedChange}
            label={`${def.label}开关`}
            disabled={def.planned}
          />
        </RowShell>
      )
    case 'select': {
      const options = toSelectOptions(def.options)
      return (
        <RowShell {...def}>
          {def.options.length > 0 && (
            <Select
              aria-label={def.label}
              value={String(def.value)}
              disabled={def.planned}
              options={options}
              onChange={(e) => {
                const raw = e.target.value
                // 数字枚举还原类型
                const match = def.options.find((o) => String(o.value) === raw)
                if (match) def.onChange(match.value)
              }}
            />
          )}
        </RowShell>
      )
    }
    case 'action':
      return (
        <RowShell {...def}>
          <Button
            variant={def.danger === true ? 'danger' : 'secondary'}
            size="sm"
            disabled={def.planned}
            onClick={def.action}
          >
            {def.buttonText}
          </Button>
        </RowShell>
      )
    case 'custom':
      return <>{def.node}</>
  }
}

/** 列表渲染（分类页主体）：分组内行间用分隔线（Folo 内容区观感）。 */
export function SettingItemList({ items }: { items: SettingItemDef[] }) {
  return (
    <div className="divide-y divide-[var(--lumi-separator)]">
      {items.map((item, i) => {
        // 分组标题不参与 divide（标题自带 margin 隔断）
        const isTitle = item.type === 'title'
        return (
          <div
            key={item.type === 'title' ? `t-${item.value}` : `i-${i}`}
            className={cx(isTitle && 'border-t-0 [&&:not(:first-child)]:pt-0')}
          >
            <SettingItem def={item} />
          </div>
        )
      })}
    </div>
  )
}
