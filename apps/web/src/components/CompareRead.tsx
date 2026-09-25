/** F016 双篇对照 —— 恰好选中 2 条时的并排阅读（桌面）/ A·B 切换（移动）。
 *
 * 复用现有 Reader 的安全渲染层（ArticleContent：DOMPurify 唯一注入点），
 * 不复制任何 HTML 渲染实现；桌面两实例独立滚动；移动端 A/B 切换条保留
 * 各自滚动位置；关闭恢复原列表并移除本面板创建的两条详情查询缓存。
 *
 * N106 工作区双栏对读：``anchorSync`` 开放手动锚点同步（A→B 滚动跳转
 * 按百分比落点）；iPad 横屏（≥ 阈值宽度）双栏可用；窄屏沿用既有 A/B
 * 切换（无障碍 tablist 语义不变）。
 * N107 窗格休眠：每个窗格空闲超阈值（默认 10 分钟）真实卸载正文 DOM
 * （内存保留滚动位置），交互唤醒后恢复——见 lib/pane-hibernate.ts。 */

import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ArrowDownToLine, X, Zap } from 'lucide-react'
import { useEntryDetail } from '../api/queries'
import { useIsMobile } from '../lib/use-is-mobile'
import {
  PANE_HIBERNATE_IDLE_MS,
  usePaneHibernate,
} from '../lib/pane-hibernate'
import ArticleContent from './ArticleContent'
import { Button } from './ui/Button'
import { Skeleton } from './ui/Skeleton'
import { cx } from './ui/cx'

/** 休眠占位符（真实卸载正文后的轻量替身；点击/聚焦唤醒）。 */
function HibernatePlaceholder({ onWake }: { onWake: () => void }) {
  return (
    <button
      type="button"
      data-testid="pane-hibernate-placeholder"
      onClick={onWake}
      onFocus={onWake}
      className={cx(
        'flex h-32 w-full flex-col items-center justify-center gap-1 rounded-[var(--lumi-radius-lg)]',
        'border border-dashed border-[var(--lumi-border)] text-xs text-[var(--lumi-text-tertiary)]',
      )}
    >
      <Zap aria-hidden className="size-4" />
      窗格已休眠（正文已释放，滚动位置已保存）——点击唤醒
    </button>
  )
}

function ComparePane({
  entryRef,
  active,
  idleMs = PANE_HIBERNATE_IDLE_MS,
  onHibernate,
  onWake,
}: {
  entryRef: string
  active: boolean
  /** 测试注入的空闲阈值（默认 10 分钟）。 */
  idleMs?: number
  onHibernate?: () => void
  onWake?: () => void
}) {
  const detail = useEntryDetail(entryRef)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const { hibernated, containerRef, wake: wakePane } = usePaneHibernate({
    idleMs,
    onHibernate,
    onWake,
  })
  const scrollElementRef = (node: HTMLDivElement | null) => {
    scrollRef.current = node
    containerRef.current = node
  }

  const wake = () => {
    wakePane()
    onWake?.()
  }

  if (detail.isPending) {
    return (
      <div
        data-testid={`compare-pane-${entryRef}`}
        className={cx('min-w-0 flex-1 overflow-y-auto p-4', !active && 'hidden')}
      >
        <Skeleton className="h-6 w-2/3" />
        <Skeleton className="mt-2 h-40 w-full" />
      </div>
    )
  }
  if (detail.isError) {
    return (
      <div
        data-testid={`compare-pane-${entryRef}`}
        className={cx('min-w-0 flex-1 p-4', !active && 'hidden')}
      >
        <p role="alert" className="text-sm text-[var(--lumi-danger)]">
          这一篇加载失败：{detail.error instanceof Error ? detail.error.message : '请重试。'}
        </p>
      </div>
    )
  }
  return (
    <div
      ref={scrollElementRef}
      data-testid={`compare-pane-${entryRef}`}
      data-compare-scroll=""
      className={cx(
        'min-w-0 flex-1 overflow-y-auto px-4 py-3',
        // 移动端 A/B 切换：隐藏非活动侧（display:none 保留其滚动位置）
        !active && 'hidden',
      )}
    >
      {hibernated ? (
        <HibernatePlaceholder onWake={wake} />
      ) : (
        detail.data !== undefined && <ArticleContent detail={detail.data} />
      )}
    </div>
  )
}

export default function CompareRead({
  refs,
  onClose,
  anchorSync = false,
  idleMs = PANE_HIBERNATE_IDLE_MS,
}: {
  refs: [string, string]
  onClose: () => void
  /** N106：工作区对读模式——显示手动锚点同步按钮（A→B 滚动跳转）。 */
  anchorSync?: boolean
  /** N107：窗格空闲休眠阈值（测试注入）。 */
  idleMs?: number
}) {
  const isMobile = useIsMobile()
  const [a, b] = refs
  const [activeSide, setActiveSide] = useState<'a' | 'b'>('a')
  const queryClient = useQueryClient()
  const sectionRef = useRef<HTMLElement | null>(null)

  // 关闭清理：移除本面板引入的两条详情缓存（避免对照打开的大正文
  // 长期占用内存；常规 Reader 的缓存策略不受影响）。
  useEffect(() => {
    return () => {
      queryClient.removeQueries({ queryKey: ['entry', a] })
      queryClient.removeQueries({ queryKey: ['entry', b] })
    }
  }, [a, b, queryClient])

  // N106：手动锚点同步——A 的滚动百分比落到 B（显式按钮触发，绝不
  // 自动跟随：双栏独立阅读是默认语义）。
  const syncAnchorAToB = () => {
    const section = sectionRef.current
    if (section === null) return
    const panes = section.querySelectorAll<HTMLElement>('[data-compare-scroll]')
    const source = panes[0]
    const target = panes[1]
    if (!source || !target || source.scrollHeight <= target.clientHeight) return
    const fraction =
      source.scrollTop / Math.max(source.scrollHeight - source.clientHeight, 1)
    target.scrollTop =
      fraction * Math.max(target.scrollHeight - target.clientHeight, 1)
  }

  return (
    <section
      ref={sectionRef}
      aria-label="对照阅读"
      data-testid="compare-read"
      className="flex h-full min-h-0 flex-col"
    >
      <div className="flex items-center gap-2 border-b border-[var(--lumi-border)] px-3 py-1.5">
        {isMobile ? (
          <div className="flex gap-1" role="tablist" aria-label="对照切换">
            <Button
              size="sm"
              variant={activeSide === 'a' ? 'primary' : 'ghost'}
              aria-pressed={activeSide === 'a'}
              onClick={() => setActiveSide('a')}
            >
              A 篇
            </Button>
            <Button
              size="sm"
              variant={activeSide === 'b' ? 'primary' : 'ghost'}
              aria-pressed={activeSide === 'b'}
              onClick={() => setActiveSide('b')}
            >
              B 篇
            </Button>
          </div>
        ) : (
          <span className="text-xs text-[var(--lumi-text-tertiary)]">
            对照阅读（两篇独立滚动；关闭恢复原列表）
          </span>
        )}
        {anchorSync && (
          <Button
            size="sm"
            variant="secondary"
            data-testid="compare-anchor-sync"
            aria-label="把 A 篇滚动位置同步到 B 篇"
            onClick={syncAnchorAToB}
          >
            <ArrowDownToLine aria-hidden className="size-4" />
            锚点同步 A→B
          </Button>
        )}
        <span className="flex-1" />
        <button
          type="button"
          aria-label="关闭对照阅读"
          onClick={onClose}
          className="flex min-h-11 min-w-11 items-center justify-center rounded-full text-[var(--lumi-text-tertiary)] hover:bg-[var(--lumi-surface-hover)]"
        >
          <X aria-hidden className="size-4" />
        </button>
      </div>
      <div
        className={cx(
          'min-h-0 flex-1',
          isMobile ? 'flex' : 'grid grid-cols-2 divide-x divide-[var(--lumi-separator)]',
        )}
      >
        <ComparePane entryRef={a} active={!isMobile || activeSide === 'a'} idleMs={idleMs} />
        <ComparePane entryRef={b} active={!isMobile || activeSide === 'b'} idleMs={idleMs} />
      </div>
    </section>
  )
}
