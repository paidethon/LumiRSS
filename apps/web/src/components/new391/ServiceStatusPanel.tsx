/** ServiceStatusPanel — NEW-397 实例服务状态页。
 *
 * 只报告本地真实检测与最近检测时间；不虚构可用率、不做网络探测。
 * 「立即检测」执行一次本地检测并落台账。
 */

import { useMutation, useQuery } from '@tanstack/react-query'
import {
  fetchServiceStatus,
  runServiceStatusCheck,
  type ServiceStatusSurface,
} from '../../api/new391'
import { Button } from '../ui/Button'
import { NoteText, StatusLine } from './parts'

const STATUS_LABELS: Record<string, string> = {
  ok: '正常',
  unconfigured: '未配置',
  fail: '异常',
  unknown: '未检测',
}

function SurfaceRow({ surface }: { surface: ServiceStatusSurface }) {
  return (
    <li
      data-n391-status-surface={surface.key}
      className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-medium text-[var(--lumi-text-primary)]">
          {surface.label}
        </span>
        <span
          data-n391-status-value={surface.key}
          className="text-xs text-[var(--lumi-text-secondary)]"
        >
          {STATUS_LABELS[surface.status] ?? surface.status}
        </span>
      </div>
      {surface.detail && <NoteText>{surface.detail}</NoteText>}
      <NoteText>
        最近检测：{surface.checkedAt ?? '从未检测'}
      </NoteText>
    </li>
  )
}

export function ServiceStatusPanel() {
  const status = useQuery({
    queryKey: ['new391', 'service-status'],
    queryFn: fetchServiceStatus,
  })
  const check = useMutation({
    mutationFn: runServiceStatusCheck,
    onSuccess: () => {
      void status.refetch()
    },
  })
  if (status.isLoading) {
    return (
      <div data-n391-panel="service-status">
        <StatusLine tone="info">正在加载服务状态…</StatusLine>
      </div>
    )
  }
  if (status.isError) {
    return (
      <div data-n391-panel="service-status">
        <StatusLine tone="error">服务状态加载失败。</StatusLine>
      </div>
    )
  }
  return (
    <div data-n391-panel="service-status" className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <NoteText>本页只报告本地真实检测结果，不提供可用率百分比。</NoteText>
        <Button size="sm" loading={check.isPending} onClick={() => check.mutate()}>
          立即检测
        </Button>
      </div>
      {check.isError && (
        <StatusLine tone="error">检测执行失败，请稍后重试。</StatusLine>
      )}
      <ul className="flex flex-col gap-2">
        {status.data?.surfaces.map((surface) => (
          <SurfaceRow key={surface.key} surface={surface} />
        ))}
      </ul>
      {status.data?.notes.map((note) => (
        <NoteText key={note}>{note}</NoteText>
      ))}
    </div>
  )
}
