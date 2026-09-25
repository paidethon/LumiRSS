/** WhatsNewTour — N198 版本差异功能导览（post-update tour card）。
 *
 * 数据面：GET /api/v1/whats-new?sinceVersion=<设备已看版本>（adminOnly
 * 条目由服务端按角色过滤——成员的响应里根本没有这些条目）。BFF 无
 * 清单文件 / 未登录 401 / 网络失败 → 组件零渲染（导览是锦上添花，
 * 绝不打扰阅读）。
 *
 * 设备本地状态（localStorage，绝不上传）：
 * - seenVersion：上次确认看过的清单版本（请求参数，命中即空导览）；
 * - dismissedVersion：手动「关闭导览」时的版本（该版本不再自动弹出）；
 * - readIds：逐项已读的功能 id（「逐项已读」持久化到本设备）。
 * 状态推进只在本组件发生；列表渲染对响应形状容错（client 已归一）。
 */

import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X } from 'lucide-react'

import { getWhatsNew, type WhatsNewFeature } from '../api/client'
import { Button } from './ui/Button'

export const WHATS_NEW_STORAGE_KEY = 'lumirss-whats-new-v1'

export interface WhatsNewLocalState {
  seenVersion: string | null
  dismissedVersion: string | null
  readIds: string[]
}

const EMPTY_LOCAL: WhatsNewLocalState = { seenVersion: null, dismissedVersion: null, readIds: [] }

export function loadWhatsNewLocal(): WhatsNewLocalState {
  try {
    const raw = window.localStorage.getItem(WHATS_NEW_STORAGE_KEY)
    if (raw === null) return { ...EMPTY_LOCAL, readIds: [] }
    const data = JSON.parse(raw) as Partial<WhatsNewLocalState>
    return {
      seenVersion: typeof data.seenVersion === 'string' ? data.seenVersion : null,
      dismissedVersion: typeof data.dismissedVersion === 'string' ? data.dismissedVersion : null,
      readIds: Array.isArray(data.readIds) ? data.readIds.filter((id) => typeof id === 'string') : [],
    }
  } catch {
    return { ...EMPTY_LOCAL, readIds: [] }
  }
}

export function saveWhatsNewLocal(state: WhatsNewLocalState): void {
  try {
    window.localStorage.setItem(WHATS_NEW_STORAGE_KEY, JSON.stringify(state))
  } catch {
    // 存储不可用（隐私模式等）：导览仍可用，只是不持久。
  }
}

function FeatureRow({
  feature,
  read,
  onToggleRead,
}: {
  feature: WhatsNewFeature
  read: boolean
  onToggleRead: () => void
}) {
  return (
    <li className="flex items-start gap-2 py-1.5" data-testid="whats-new-item">
      <input
        id={`whats-new-read-${feature.id}`}
        type="checkbox"
        checked={read}
        onChange={onToggleRead}
        className="mt-0.5 size-4 shrink-0"
        aria-label={`已读：${feature.title}`}
      />
      <label htmlFor={`whats-new-read-${feature.id}`} className="min-w-0 flex-1 cursor-pointer">
        <span
          className={`block text-sm leading-relaxed ${
            read
              ? 'text-[var(--lumi-text-tertiary)] line-through'
              : 'text-[var(--lumi-text-primary)]'
          }`}
        >
          {feature.title}
        </span>
        {feature.entry !== '' && (
          <span className="mt-0.5 block text-xs text-[var(--lumi-text-tertiary)]">
            入口：{feature.entry}
          </span>
        )}
      </label>
      {feature.adminOnly === true && (
        <span className="shrink-0 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-px text-[11px] leading-4 text-[var(--lumi-text-tertiary)]">
          管理员
        </span>
      )}
    </li>
  )
}

export default function WhatsNewTour() {
  const [local, setLocal] = useState<WhatsNewLocalState>(loadWhatsNewLocal)
  const tour = useQuery({
    queryKey: ['whats-new', local.seenVersion],
    queryFn: ({ signal }) => getWhatsNew(local.seenVersion, signal),
    staleTime: 10 * 60_000,
    retry: false,
  })

  const version = tour.data?.version ?? null
  const features = tour.data?.features ?? []

  // 已看过当前版本（服务端返回空导览）：把 seenVersion 固化，避免之后
  // 每次都以「未知版本」重新拉全量。
  useEffect(() => {
    if (version !== null && features.length === 0 && local.seenVersion !== version) {
      setLocal((prev) => {
        const next = { ...prev, seenVersion: version }
        saveWhatsNewLocal(next)
        return next
      })
    }
  }, [version, features.length, local.seenVersion])

  if (tour.isPending || tour.isError) return null // 加载中/失败（401、离线）→ 静默
  if (version === null) return null // BFF 无清单 → 诚实隐藏
  if (features.length === 0) return null // 版本已看过 → 无导览
  if (local.dismissedVersion === version) return null // 本设备已关闭该版本导览

  const update = (mutate: (prev: WhatsNewLocalState) => WhatsNewLocalState) => {
    setLocal((prev) => {
      const next = mutate(prev)
      saveWhatsNewLocal(next)
      return next
    })
  }

  const unreadCount = features.filter((feature) => !local.readIds.includes(feature.id)).length

  return (
    <div
      role="region"
      aria-label={`版本 ${version} 新功能导览`}
      data-testid="whats-new-tour"
      className="fixed bottom-4 left-1/2 z-[calc(var(--lumi-z-dialog)_+_1)] flex max-h-[70dvh] w-[min(94vw,30rem)] -translate-x-1/2 flex-col rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] p-4 shadow-[var(--lumi-shadow-dialog)]"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-[var(--lumi-text-primary)]">
            本次更新带来了 {features.length} 项新功能
          </p>
          <p className="mt-0.5 text-xs text-[var(--lumi-text-tertiary)]">
            版本 {version}
            {unreadCount > 0 ? ` · ${unreadCount} 项待读` : ' · 全部已读'}
          </p>
        </div>
        <button
          type="button"
          onClick={() =>
            update((prev) => ({ ...prev, seenVersion: version, dismissedVersion: version }))
          }
          aria-label="关闭导览"
          data-testid="whats-new-close"
          className="flex size-11 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-text-primary)] focus-visible outline-2 -outline-offset-1 outline-[var(--lumi-focus-ring)]"
        >
          <X aria-hidden className="size-4" />
        </button>
      </div>
      <ul className="mt-2 flex-1 divide-y divide-[var(--lumi-separator)] overflow-y-auto">
        {features.map((feature) => (
          <FeatureRow
            key={feature.id}
            feature={feature}
            read={local.readIds.includes(feature.id)}
            onToggleRead={() =>
              update((prev) => ({
                ...prev,
                readIds: prev.readIds.includes(feature.id)
                  ? prev.readIds.filter((id) => id !== feature.id)
                  : [...prev.readIds, feature.id],
              }))
            }
          />
        ))}
      </ul>
      <div className="mt-3 flex justify-end">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => update((prev) => ({ ...prev, seenVersion: version, dismissedVersion: version }))}
          data-testid="whats-new-dismiss"
          className="min-h-11"
        >
          关闭导览
        </Button>
      </div>
    </div>
  )
}
