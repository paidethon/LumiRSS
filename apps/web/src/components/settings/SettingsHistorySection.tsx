/** SettingsHistorySection — F33：设置变更历史与回退。
 *
 * 展示最近 10 次 portable 设置变更（只含实际变化的键，无密钥字段）；
 * 「回退」把该条记录的 before 值重新应用——若某键之后又被改过则跳过
 * 并如实列出（回退不覆盖新修改）。 */

import { useQuery } from '@tanstack/react-query'

import { getSettingsHistory, revertSettingsHistory } from '../../api/client'
import { Button } from '../ui/Button'

function fmtValue(value: object | undefined): string {
  if (value === undefined || value === null) return '（空）'
  return String(value)
}

export function SettingsHistorySection() {
  const history = useQuery({
    queryKey: ['settings-history'],
    queryFn: ({ signal }) => getSettingsHistory(signal, 10),
    staleTime: 30_000,
  })

  if (history.isPending) return null
  if (history.isError) {
    return (
      <p className="text-xs text-[var(--lumi-text-tertiary)]">设置历史加载失败。</p>
    )
  }
  const items = history.data.items
  if (items.length === 0) {
    return (
      <div className="py-3" data-settings-history>
        <div className="text-sm font-medium text-[var(--lumi-text-primary)]">设置变更历史</div>
        <p className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">
          还没有可回退的设置变更；每次修改外观/阅读等设置后会记录一条（最多 20 条）。
        </p>
      </div>
    )
  }
  return (
    <div className="py-3" data-settings-history>
      <div className="text-sm font-medium text-[var(--lumi-text-primary)]">设置变更历史</div>
      <ul className="mt-2 flex flex-col divide-y divide-[var(--lumi-separator)]">
        {items.map((entry) => {
          const keys = Object.keys(entry.diff)
          return (
            <li key={entry.id} className="flex min-h-11 flex-wrap items-center justify-between gap-2 py-2">
              <div className="min-w-0">
                <div className="text-xs text-[var(--lumi-text-primary)]">
                  {entry.action === 'revert' ? '回退' : '修改'} · {keys.length} 个键 ·{' '}
                  {entry.changedAt.slice(0, 16).replace('T', ' ')}
                </div>
                <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">
                  {keys.map((key) => (
                    <span key={key}>
                      {key}: {fmtValue(entry.diff[key] as object | undefined)}
                    </span>
                  ))}
                </div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => revertSettingsHistory(entry.id)}
              >
                回退
              </Button>
            </li>
          )
        })}
      </ul>
      <p className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">
        回退不覆盖之后的新修改（被改过的键会跳过）；便携设置不含任何密钥。
      </p>
    </div>
  )
}
