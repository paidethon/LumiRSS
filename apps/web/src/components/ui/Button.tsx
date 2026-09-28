/** Button primitive — 0009 Gate 1。
 *
 * 语义变体（variant）× 语义尺寸（size），颜色全部来自 --lumi-* token。
 * focus-visible 用统一 focus-ring token；动效时长用 motion token；
 * 禁止业务逻辑进 primitives。
 *
 * FIX-115 loading：加载反馈契约——
 * - 文字标签永不消失（此前多处 `{pending ? <Spinner/> : '保存'}` 把
 *   标签整个换成 spinner：宽度跳变 + 文字消失 + 无可访问反馈）；
 * - spinner 内联渲染在标签前（aria-hidden，视觉尺寸 = 文本行高）；
 * - aria-busy="true" + disabled（防重复提交；读屏可感知忙碌态）。 */

import type { ButtonHTMLAttributes } from 'react'
import { Loader2 } from 'lucide-react'
import { cx } from './cx'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  /** 加载中：保留标签 + 内联 spinner + aria-busy + disabled（FIX-115） */
  loading?: boolean
}

const variantClasses: Record<Variant, string> = {
  // 主操作：Accent 实底
  primary:
    'bg-[var(--lumi-accent)] text-[var(--lumi-accent-contrast)] hover:bg-[var(--lumi-accent-hover)] active:bg-[var(--lumi-accent-pressed)] border border-transparent',
  // 次操作：surface + border
  secondary:
    'bg-[var(--lumi-surface)] text-[var(--lumi-text-primary)] border border-[var(--lumi-border)] hover:bg-[var(--lumi-surface-hover)] active:bg-[var(--lumi-surface-pressed)]',
  // 弱操作：无底无框（hover 才有 surface）
  ghost:
    'bg-transparent text-[var(--lumi-text-primary)] border border-transparent hover:bg-[var(--lumi-surface-hover)] active:bg-[var(--lumi-surface-pressed)]',
  // 破坏性操作（Spec：分隔 + 需确认的场景使用）
  danger:
    'bg-[var(--lumi-danger)] text-[var(--lumi-danger-contrast)] border border-transparent hover:bg-[var(--lumi-danger-hover)]',
}

const sizeClasses: Record<Size, string> = {
  sm: 'min-h-8 px-2.5 text-sm gap-1.5',
  md: 'min-h-10 px-3.5 text-sm gap-2',
}

// 共态：圆角 md（8px，Spec §设计规格）+ motion-fast + focus ring
const base =
  'inline-flex items-center justify-center rounded-[var(--lumi-radius-md)] font-medium transition-colors duration-[var(--lumi-motion-fast)] select-none focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)] disabled:cursor-not-allowed disabled:opacity-50 disabled:pointer-events-none'

export function Button({
  variant = 'secondary',
  size = 'md',
  type = 'button',
  loading = false,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      aria-busy={loading || undefined}
      disabled={disabled === undefined ? loading : disabled || loading}
      className={cx(base, variantClasses[variant], sizeClasses[size], className)}
      {...rest}
    >
      {loading && (
        <Loader2
          aria-hidden="true"
          data-loading-spinner=""
          className="size-4 shrink-0 animate-spin"
        />
      )}
      {children}
    </button>
  )
}
