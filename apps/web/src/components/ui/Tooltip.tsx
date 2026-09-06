/** Tooltip primitive — Base UI 行为底座（原 0009 Gate 1 CSS-only 实现迁移）。
 *
 * hover / 键盘 focus 触发、Escape 关闭、portal + Floating UI 定位
 * （含视口碰撞翻转，修复旧实现溢出滚动容器被裁切的问题）、trigger 与
 * popup 的 aria-describedby 关联由 Base UI 自动维护（修复旧实现把
 * describedby 挂在 contents span 上导致的关联断裂）。
 * 视觉保持 Lumi 原样：--lumi-* token、上方居中、6px 间距、快速淡入。
 * 触发元素通过 render prop 合成（通常是 IconButton，需自带 aria-label）。 */

import { type ReactElement, type ReactNode } from 'react'
import { Tooltip as BaseTooltip } from '@base-ui/react/tooltip'
import { cx } from './cx'

export interface TooltipProps {
  /** 触发元素（通常是 IconButton；必须是可渲染的单个元素） */
  children: ReactElement
  /** 提示文本 */
  content: ReactNode
}

export function Tooltip({ children, content }: TooltipProps) {
  return (
    <BaseTooltip.Provider delay={0} closeDelay={0}>
      <BaseTooltip.Root>
        <BaseTooltip.Trigger render={children} />
        <BaseTooltip.Portal>
          <BaseTooltip.Positioner
            side="top"
            align="center"
            sideOffset={6}
            collisionPadding={8}
            className="z-[var(--lumi-z-tooltip)]"
          >
            <BaseTooltip.Popup
              className={cx(
                'rounded-[var(--lumi-radius-sm)] bg-[var(--lumi-text-primary)] px-2 py-1 text-xs text-[var(--lumi-surface)]',
                'whitespace-nowrap',
                'transition-opacity duration-[var(--lumi-motion-fast)]',
                'data-starting-style:opacity-0 data-ending-style:opacity-0',
              )}
            >
              {content}
            </BaseTooltip.Popup>
          </BaseTooltip.Positioner>
        </BaseTooltip.Portal>
      </BaseTooltip.Root>
    </BaseTooltip.Provider>
  )
}
