/** FirstRunChecklist — F40 最小首启向导：可跳过、可重进。
 *
 * 触发条件：localStorage 无 dismissed 标记 + FreshRSS 尚无任何订阅。
 * 三步清单（连接 FreshRSS → 添加第一个来源 → 可选阅读设置/日报），
 * 每步是真实入口的指引文字；勾选自由、可整体关闭（不再出现）。
 * 不自动订阅任何来源、不调用付费 API。 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X } from 'lucide-react'

import { getFeeds } from '../api/client'

const DISMISS_KEY = 'lumirss-first-run-dismissed'

export function useFirstRunVisible(): boolean {
  const [dismissed] = useState(() => localStorage.getItem(DISMISS_KEY) === '1')
  const feeds = useQuery({
    queryKey: ['feeds'],
    queryFn: ({ signal }) => getFeeds(signal),
    enabled: !dismissed,
  })
  const noFeeds = feeds.data !== undefined && feeds.data.length === 0
  return !dismissed && noFeeds
}

export function FirstRunChecklist({ onClose }: { onClose: () => void }) {
  const [step1, setStep1] = useState(false)
  const [step2, setStep2] = useState(false)

  function dismissForever() {
    localStorage.setItem(DISMISS_KEY, '1')
    onClose()
  }

  return (
    <div
      className="mb-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3"
      data-first-run-checklist
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-[var(--lumi-text-primary)]">
          开始使用（三步）
        </span>
        <button
          type="button"
          aria-label="关闭向导"
          className="text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-text-primary)]"
          onClick={dismissForever}
        >
          <X aria-hidden className="size-4" />
        </button>
      </div>
      <ol className="mt-2 flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
        <li>
          <label className="flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={step1}
              onChange={(e) => setStep1(e.target.checked)}
            />
            FreshRSS 已连通（订阅中心可打开、来源可见）
          </label>
        </li>
        <li>
          <label className="flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={step2}
              onChange={(e) => setStep2(e.target.checked)}
            />
            已添加第一个来源（下方「添加来源」按钮）
          </label>
        </li>
        <li className="pl-6">
          可选：设置 → 通用 调整阅读外观；设置 → 邮件简报 可选启用 GPT 日报。
          RSS 自动更新由 FreshRSS 容器 cron 负责（CRON_MIN）。
        </li>
      </ol>
    </div>
  )
}
