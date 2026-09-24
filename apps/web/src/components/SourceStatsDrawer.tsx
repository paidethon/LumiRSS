/** F023/F024/F025/F026/F035/F037/F038 来源统计与工具抽屉。
 *
 * 一个入口集中承载订阅行的「低频但有用」信息，不堆常驻按钮：
 * - F023 最近同步时间（投影口径诚实：null = 投影未覆盖，不冒充「从未」）
 * - F024 近 30 天发布频率柱状图（稀疏分桶前端补零；投影未覆盖 → 诚实空态）
 * - F025 日均/周均（由同一分桶计算，四舍五入到 1 位）
 * - F035 30 天更新日历（热力格，深浅按当日量分级）
 * - F026 一键打开来源主页（feed 地址的 http(s) origin）
 * - F037 一键复制 feed 原始地址
 * - F038 QR code（uqr renderSVG；扫码在移动端打开同一 feed）
 *
 * 数据 = GET /sources/volume?days=30&daily=true（派生投影聚合，只读，
 * 不复制 RSS 全文）。 */

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CalendarDays, Check, Copy, ExternalLink, QrCode } from 'lucide-react'
import { renderSVG } from 'uqr'
import { getSubscriptionVolume } from '../api/client'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { EmptyState } from './ui/EmptyState'
import { Skeleton } from './ui/Skeleton'

const WINDOW_DAYS = 30

function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime()
  const minutes = Math.floor(diffMs / 60_000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
}

/** 稀疏分桶 → 30 槽（旧→新）补零数组。 */
function dailySlots(daily: { date: string; count: number }[]): number[] {
  const byDate = new Map(daily.map((b) => [b.date, b.count]))
  const slots: number[] = []
  const now = new Date()
  for (let i = WINDOW_DAYS - 1; i >= 0; i -= 1) {
    const d = new Date(now)
    d.setUTCDate(d.getUTCDate() - i)
    slots.push(byDate.get(d.toISOString().slice(0, 10)) ?? 0)
  }
  return slots
}

function originOf(feedUrl: string): string | null {
  try {
    const url = new URL(feedUrl)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.origin : null
  } catch {
    return null
  }
}

export function SourceStatsDrawer({
  open,
  onClose,
  feedUrl,
  title,
}: {
  open: boolean
  onClose: () => void
  feedUrl: string
  title: string
}) {
  const volume = useQuery({
    queryKey: ['sources-volume', WINDOW_DAYS, 'daily'],
    queryFn: ({ signal }) => getSubscriptionVolume(signal, WINDOW_DAYS, true),
    enabled: open,
    staleTime: 60_000,
  })
  const [copied, setCopied] = useState(false)
  const [qrShown, setQrShown] = useState(false)

  const item = useMemo(
    () =>
      volume.data?.items?.find((candidate) => candidate.feedUrl === feedUrl) ?? null,
    [volume.data, feedUrl],
  )
  const slots = useMemo(
    () => (item?.daily ? dailySlots(item.daily) : null),
    [item],
  )
  const totals = useMemo(() => {
    if (!slots) return null
    const sum = slots.reduce((acc, n) => acc + n, 0)
    return {
      sum,
      perDay: sum / WINDOW_DAYS,
      perWeek: (sum / WINDOW_DAYS) * 7,
    }
  }, [slots])
  const maxSlot = slots ? Math.max(1, ...slots) : 1
  const origin = originOf(feedUrl)

  const copyFeed = async () => {
    await navigator.clipboard.writeText(feedUrl)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={`「${title}」统计与工具`}
      panelClassName="max-w-lg"
    >
      {volume.isLoading ? (
        <div className="flex flex-col gap-2 py-2" data-testid="source-stats-loading">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : volume.isError ? (
        <EmptyState
          icon={<CalendarDays aria-hidden className="size-6" />}
          title="统计加载失败"
          description="收件量投影暂时不可用，稍后重试。"
        />
      ) : !item || item.daily === null ? (
        <EmptyState
          icon={<CalendarDays aria-hidden className="size-6" />}
          title="暂无投影数据"
          description="该订阅还没有被搜索投影覆盖；有新条目入库后这里会出现频率统计。"
        />
      ) : (
        <div className="flex flex-col gap-4 py-1">
          <section>
            <h4 className="text-xs font-medium text-[var(--lumi-text-secondary)]">
              最近同步
            </h4>
            <p className="mt-1 text-sm text-[var(--lumi-text-primary)]">
              {item.lastSyncedAt ? (
                <>
                  投影入库 <time dateTime={item.lastSyncedAt}>{relativeTime(item.lastSyncedAt)}</time>
                </>
              ) : (
                '投影未覆盖（不冒充「从未同步」）'
              )}
            </p>
          </section>

          <section>
            <h4 className="text-xs font-medium text-[var(--lumi-text-secondary)]">
              近 30 天发布频率
            </h4>
            {/* F024 柱状图：纯 div 柱，语义由表格外的文字摘要承担 */}
            <div
              className="mt-2 flex h-16 items-end gap-[2px]"
              role="img"
              aria-label={`近 30 天共 ${totals?.sum ?? 0} 条，日均 ${totals ? totals.perDay.toFixed(1) : '—'} 条`}
              data-testid="source-volume-chart"
            >
              {slots!.map((count, index) => (
                <span
                  key={index}
                  className="min-w-[4px] flex-1 rounded-t-[2px] bg-[var(--lumi-accent)]"
                  style={{ height: `${Math.max(4, (count / maxSlot) * 100)}%`, opacity: count === 0 ? 0.25 : 1 }}
                />
              ))}
            </div>
            {/* F025 日均/周均 */}
            <p className="mt-1.5 text-xs text-[var(--lumi-text-secondary)]">
              共 {totals?.sum ?? 0} 条 · 日均 {totals ? totals.perDay.toFixed(1) : '—'} 条 · 周均{' '}
              {totals ? totals.perWeek.toFixed(1) : '—'} 条
            </p>
          </section>

          <section>
            <h4 className="text-xs font-medium text-[var(--lumi-text-secondary)]">
              30 天更新日历
            </h4>
            {/* F035 热力格：4 级深浅 */}
            <div className="mt-2 flex flex-wrap gap-[3px]" data-testid="source-volume-heatmap">
              {slots!.map((count, index) => (
                <span
                  key={index}
                  title={`${count} 条`}
                  className="size-[10px] rounded-[2px] bg-[var(--lumi-accent)]"
                  style={{ opacity: count === 0 ? 0.12 : 0.3 + (count / maxSlot) * 0.7 }}
                />
              ))}
            </div>
          </section>

          <section className="flex flex-col gap-2 border-t border-[var(--lumi-border)] pt-3">
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="secondary" size="sm" onClick={copyFeed}>
                {copied ? <Check aria-hidden className="size-4" /> : <Copy aria-hidden className="size-4" />}
                {copied ? '已复制' : '复制 Feed 地址'}
              </Button>
              {origin !== null && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => window.open(origin, '_blank', 'noopener,noreferrer')}
                >
                  <ExternalLink aria-hidden className="size-4" />
                  来源主页
                </Button>
              )}
              <Button
                variant="secondary"
                size="sm"
                aria-expanded={qrShown}
                onClick={() => setQrShown((shown) => !shown)}
              >
                <QrCode aria-hidden className="size-4" />
                {qrShown ? '隐藏二维码' : '扫码订阅'}
              </Button>
            </div>
            {qrShown && (
              <div className="flex items-center gap-3">
                {/* uqr renderSVG：自包含 SVG 字符串；外层定宽防溢出 */}
                <div
                  className="size-40 shrink-0 [&>svg]:size-full"
                  data-testid="source-feed-qr"
                  aria-hidden
                  dangerouslySetInnerHTML={{ __html: renderSVG(feedUrl) }}
                />
                <p className="text-xs text-[var(--lumi-text-secondary)]">
                  用移动端扫码直接打开本 feed 地址。
                </p>
              </div>
            )}
          </section>
        </div>
      )}
    </Dialog>
  )
}
