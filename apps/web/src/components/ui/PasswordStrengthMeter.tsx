/** PasswordStrengthMeter — N005 本地密码强度提示（ui 原语）。
 *
 * 纯展示组件：接收 lib/password-strength 的三档结果，渲染分档条 +
 * 文案。计算完全在本地（lib 纯函数），本组件不触碰网络。 */

import { STRENGTH_TEXT, type PasswordStrength } from '../../lib/password-strength'
import { cx } from './cx'

const TIER_ORDER: PasswordStrength[] = ['weak', 'medium', 'strong']

// FIX-294：分档条纯背景承载，forced-colors 下被强制为 ButtonFace 而
// 消失——弱/中 CanvasText、强 Highlight 系统色保底（条下仍有文字兜底）。
const TIER_FILL: Record<PasswordStrength, string> = {
  weak: 'bg-[var(--lumi-danger)] forced-colors:bg-[CanvasText]',
  medium: 'bg-[var(--lumi-warning)] forced-colors:bg-[CanvasText]',
  strong: 'bg-[var(--lumi-accent-text)] forced-colors:bg-[Highlight]',
}

export function PasswordStrengthMeter({
  strength,
  id,
}: {
  strength: PasswordStrength | null
  id?: string
}) {
  if (strength === null) return null
  return (
    <div id={id} data-testid="password-strength" data-strength={strength} className="mt-1.5">
      <div className="flex gap-1" aria-hidden>
        {TIER_ORDER.map((tier) => (
          <span
            key={tier}
            className={cx(
              'h-1 flex-1 rounded-[var(--lumi-radius-full)] transition-colors duration-[var(--lumi-motion-fast)]',
              tier === strength ? TIER_FILL[strength] : 'bg-[var(--lumi-separator)]',
            )}
          />
        ))}
      </div>
      <p
        aria-live="polite"
        className="mt-1 text-xs text-[var(--lumi-text-secondary)]"
      >
        {STRENGTH_TEXT[strength]}
      </p>
    </div>
  )
}
