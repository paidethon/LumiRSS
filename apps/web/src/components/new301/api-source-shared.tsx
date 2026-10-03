/** API 来源列表 / 详情共享的小件：状态徽标、相对时间、host 提取。
 * 颜色全部 --lumi-* 语义令牌；不引入任何硬编码色。 */

import { AlertCircle, CheckCircle2 } from 'lucide-react'
import type { ReactElement } from 'react'
import type { ApiSource } from '../../api/client'
import { dateTimeFormatter } from '../../lib/date-format'
import { cx } from '../ui/cx'

/** ISO 时间戳 → 相对时间；缺失 / 无效 / 超过 30 天回退绝对时间。 */
export function formatRelative(iso: string | null | undefined): string {
  if (iso === null || iso === undefined || iso === '') return '从未'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '从未'
  const minutes = Math.floor((Date.now() - date.getTime()) / 60_000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return dateTimeFormatter.format(date)
}

/** endpoint → host（malformed 原样展示，不吞 URL）。 */
export function endpointHost(endpoint: string): string {
  try {
    return new URL(endpoint).host
  } catch {
    return endpoint
  }
}

/** lastStatus 徽标：ok=正常；fetch_failed=错误（tooltip lastError）；
 * subscribe_failed=订阅失败；其余=未运行。 */
export function StatusBadge({ source }: { source: ApiSource }): ReactElement {
  const status = source.lastStatus ?? null
  if (status === 'ok') {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-[var(--lumi-category-green)]">
        <CheckCircle2 aria-hidden className="size-3.5" />
        正常
      </span>
    )
  }
  if (status === 'fetch_failed' || status === 'subscribe_failed') {
    const detail =
      status === 'subscribe_failed'
        ? (source.subscribeError ?? source.lastError)
        : source.lastError
    return (
      <span
        title={detail ?? undefined}
        className="inline-flex cursor-help items-center gap-1 text-xs font-medium text-[var(--lumi-danger)]"
      >
        <AlertCircle aria-hidden className="size-3.5" />
        {status === 'fetch_failed' ? '错误' : '订阅失败'}
      </span>
    )
  }
  return <span className={cx('text-xs text-[var(--lumi-text-tertiary)]')}>未运行</span>
}
