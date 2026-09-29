/** NEW-251..260 研究工具组共用小件 + 数据语义色板（单一定义）。
 *
 * 色板说明：状态色是内容语义色（open/resolved/unhandled/handled 等），
 * 不是主题 token——与 AnnotationsManager 的 ANNOTATION_DOT_COLORS 同
 * 一模式：单一定义导出 + 内联 style，禁止另立同名 CSS 变量伪令牌。
 * UI 骨架（边框/文字/背景）一律用既有 --lumi-* token。 */

import type { CSSProperties, ReactNode } from 'react'

/**
 * 研究组状态徽标色映射（单一定义，内联 style 消费）。
 * 状态是反馈语义，一律用 FIX-077 统一后的既有 --lumi-* token
 * （open=accent 信息 / resolved·handled·supported·closed=success /
 * unhandled·refuted=danger / proposed=warning / retired=中性三级文本），
 * 不写死十六进制字面量（fix-071-077 守卫测试会拦截回潮）。
 */
export const RESEARCH_STATUS_COLORS: Record<string, string> = {
  open: 'var(--lumi-accent)',
  resolved: 'var(--lumi-success)',
  unhandled: 'var(--lumi-danger)',
  handled: 'var(--lumi-success)',
  proposed: 'var(--lumi-warning)',
  supported: 'var(--lumi-success)',
  refuted: 'var(--lumi-danger)',
  retired: 'var(--lumi-text-tertiary)',
  closed: 'var(--lumi-success)',
}

export function statusStyle(status: string): CSSProperties {
  const color = RESEARCH_STATUS_COLORS[status]
  if (color === undefined) return {}
  return { color, borderColor: color }
}

/** 状态徽标（小圆角描边；数据语义色来自 RESEARCH_STATUS_COLORS）。 */
export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      data-new251-badge={status}
      style={statusStyle(status)}
      className="inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-xs leading-tight"
    >
      {status}
    </span>
  )
}

/** 工具小节（标题 + 说明 + 内容）。 */
export function ToolSection({
  title,
  description,
  children,
}: {
  title: string
  description: string
  children: ReactNode
}) {
  return (
    <section
      data-new251-section=""
      className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
    >
      <h4 className="text-sm font-medium text-[var(--lumi-text-primary)]">{title}</h4>
      <p className="mt-0.5 text-xs text-[var(--lumi-text-tertiary)]">{description}</p>
      <div className="mt-3 flex flex-col gap-3">{children}</div>
    </section>
  )
}

/** 带标签的单行输入（label 显式关联，满足可访问性基线）。 */
export function TextField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
}) {
  const id = `new251-field-${label}`
  return (
    <label htmlFor={id} className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
      {label}
      <input
        id={id}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 text-sm text-[var(--lumi-text-primary)]"
      />
    </label>
  )
}

/** 带标签的多行输入。 */
export function TextAreaField({
  label,
  value,
  onChange,
  rows = 2,
  placeholder,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  rows?: number
  placeholder?: string
}) {
  const id = `new251-area-${label}`
  return (
    <label htmlFor={id} className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
      {label}
      <textarea
        id={id}
        rows={rows}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 text-sm text-[var(--lumi-text-primary)]"
      />
    </label>
  )
}

/** 带标签的下拉选择。 */
export function SelectField({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  options: { value: string; label: string }[]
}) {
  const id = `new251-select-${label}`
  return (
    <label htmlFor={id} className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
      {label}
      <select
        id={id}
        value={value}
        aria-label={label}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 text-sm text-[var(--lumi-text-primary)]"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  )
}

/** 操作结果提示行（aria-live，诚实展示成功/失败文案）。 */
export function NoticeLine({ notice }: { notice: string | null }) {
  if (notice === null) return null
  return (
    <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
      {notice}
    </p>
  )
}

/** 错误提示行。 */
export function ErrorLine({ error }: { error: unknown }) {
  if (!error) return null
  return (
    <p role="alert" className="text-xs text-[var(--lumi-danger)]">
      {error instanceof Error ? error.message : '请求失败，请稍后重试。'}
    </p>
  )
}
