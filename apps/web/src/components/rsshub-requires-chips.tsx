/** N023 RSSHub 路由依赖 chips —— curated 元数据的诚实呈现。
 *
 * 三态字段：true = 需要（accent chip）/ null = 未知（tertiary chip，
 * 绝不冒充「不需要」）/ false = 不需要（不渲染——「无需登录」不是
 * 用户此刻要扫的信息）。整个 requires 缺失（未标注路由）→ 单枚
 * 「依赖未知」chip。仅做展示，不做任何推断。
 */

import type { RssHubRequires } from '../api/types'
import { cx } from './ui/cx'

const FACETS: ReadonlyArray<{
  key: keyof RssHubRequires
  label: string
  unknownLabel: string
}> = [
  { key: 'login', label: '需要登录', unknownLabel: '登录未知' },
  { key: 'cookies', label: '需要 Cookie', unknownLabel: 'Cookie 未知' },
  { key: 'render', label: '需要浏览器渲染', unknownLabel: '渲染未知' },
  { key: 'extraService', label: '需要额外服务', unknownLabel: '额外服务未知' },
]

export function RssHubRequiresChips({
  requires,
  className,
}: {
  requires: RssHubRequires | null | undefined
  className?: string
}) {
  const chipBase =
    'shrink-0 rounded-[var(--lumi-radius-sm)] px-1.5 py-0.5 text-[10px] leading-4'
  if (requires == null) {
    return (
      <span className={cx('inline-flex flex-wrap gap-1', className)}>
        <span
          className={cx(
            chipBase,
            'bg-[var(--lumi-surface-hover)] text-[var(--lumi-text-tertiary)]',
          )}
        >
          依赖未知
        </span>
      </span>
    )
  }
  return (
    <span className={cx('inline-flex flex-wrap gap-1', className)}>
      {FACETS.map((facet) => {
        const value = requires[facet.key]
        if (value === false) return null
        if (value === true) {
          return (
            <span
              key={facet.key}
              className={cx(
                chipBase,
                'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent)]',
              )}
            >
              {facet.label}
            </span>
          )
        }
        return (
          <span
            key={facet.key}
            className={cx(
              chipBase,
              'bg-[var(--lumi-surface-hover)] text-[var(--lumi-text-tertiary)]',
            )}
          >
            {facet.unknownLabel}
          </span>
        )
      })}
    </span>
  )
}
