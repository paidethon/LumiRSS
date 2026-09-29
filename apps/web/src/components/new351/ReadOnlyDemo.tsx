/** ReadOnlyDemo — NEW-360 移动端只读演示模式（全屏隔离浮层）。
 *
 * 用隔离合成数据展示阅读与管理两个界面样本：
 * - 顶部固定横幅明确「演示模式 · 只读 · 合成数据」（不可关闭）；
 * - 阅读界面：合成条目清单 + ArticleContent 正文渲染（与真实阅读器
 *   同一渲染管线——演示即真实观感；无任何变更动作入口）；
 * - 管理界面：合成订阅源表（操作按钮一律禁用 + 说明），绝不暴露真实
 *   账户/订阅，也不需要生产截图；
 * - 只存在于当前会话（不持久化）；退出即卸载，零残留；
 * - 零网络：fetch 间谍在测试中钉定为零调用。
 */

import { useState } from 'react'
import { BookOpen, Lock, Settings2, X } from 'lucide-react'
import ArticleContent from '../ArticleContent'
import { Button } from '../ui/Button'
import { cx } from '../ui/cx'
import {
  DEMO_ENTRIES,
  DEMO_MODE_BANNER,
  DEMO_SOURCES,
  type DemoEntry,
} from '../../lib/demo-reading'

type DemoTab = 'reading' | 'management'

export function ReadOnlyDemo({ onExit }: { onExit: () => void }) {
  const [tab, setTab] = useState<DemoTab>('reading')
  const [selectedRef, setSelectedRef] = useState<string>(DEMO_ENTRIES[0]!.entryRef)
  const selected: DemoEntry =
    DEMO_ENTRIES.find((entry) => entry.entryRef === selectedRef) ?? DEMO_ENTRIES[0]!

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="只读演示模式"
      data-n360-demo=""
      className="fixed inset-0 z-50 flex flex-col bg-[var(--lumi-canvas)]"
    >
      {/* 演示横幅（不可关闭——防止误当真实界面） */}
      <div
        data-n360-banner=""
        className="flex items-center gap-2 border-b border-[var(--lumi-border)] bg-[var(--lumi-accent-soft)] px-3 py-2"
        style={{ paddingTop: 'max(0.5rem, var(--safe-top))' }}
      >
        <Lock aria-hidden className="size-4 shrink-0 text-[var(--lumi-accent-text)]" />
        <p aria-live="polite" className="min-w-0 flex-1 text-xs font-medium leading-relaxed text-[var(--lumi-accent-text)]">
          {DEMO_MODE_BANNER}
        </p>
        <Button variant="ghost" size="sm" data-testid="n360-exit" onClick={onExit}>
          <X aria-hidden className="size-3.5" />
          退出演示
        </Button>
      </div>

      {/* 界面样本切换 */}
      <div role="tablist" aria-label="演示界面" className="flex border-b border-[var(--lumi-border)] bg-[var(--lumi-surface)]">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'reading'}
          data-testid="n360-tab-reading"
          onClick={() => setTab('reading')}
          className={cx(
            'flex min-h-11 flex-1 items-center justify-center gap-1.5 text-sm font-medium transition-colors duration-[var(--lumi-motion-fast)]',
            tab === 'reading'
              ? 'border-b-2 border-[var(--lumi-accent)] text-[var(--lumi-accent-text)]'
              : 'text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)]',
          )}
        >
          <BookOpen aria-hidden className="size-4" />
          阅读界面
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'management'}
          data-testid="n360-tab-management"
          onClick={() => setTab('management')}
          className={cx(
            'flex min-h-11 flex-1 items-center justify-center gap-1.5 text-sm font-medium transition-colors duration-[var(--lumi-motion-fast)]',
            tab === 'management'
              ? 'border-b-2 border-[var(--lumi-accent)] text-[var(--lumi-accent-text)]'
              : 'text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)]',
          )}
        >
          <Settings2 aria-hidden className="size-4" />
          管理界面
        </button>
      </div>

      {tab === 'reading' ? (
        <div className="flex min-h-0 flex-1 flex-col" data-n360-reading="">
          {/* 合成条目清单（只读：无勾选/无批量/无动作） */}
          <ul aria-label="演示条目" className="border-b border-[var(--lumi-border)] bg-[var(--lumi-surface)]">
            {DEMO_ENTRIES.map((entry) => (
              <li key={entry.entryRef}>
                <button
                  type="button"
                  aria-current={entry.entryRef === selected.entryRef ? 'true' : undefined}
                  onClick={() => setSelectedRef(entry.entryRef)}
                  className={cx(
                    'flex w-full flex-col gap-0.5 px-3 py-2 text-left transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                    entry.entryRef === selected.entryRef && 'bg-[var(--lumi-surface-hover)]',
                  )}
                >
                  <span className="truncate text-sm font-medium text-[var(--lumi-text-primary)]">
                    {entry.title}
                  </span>
                  <span className="truncate text-xs text-[var(--lumi-text-tertiary)]">
                    {entry.feedTitle} · {entry.snippet}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
            {/* 同一正文渲染管线（演示数据只读展示；无已读/收藏入口） */}
            <h1 className="mb-2 text-lg font-semibold leading-snug text-[var(--lumi-text-primary)]">
              {selected.title}
            </h1>
            <p className="mb-4 text-xs text-[var(--lumi-text-tertiary)]">
              {selected.feedTitle} · {selected.author ?? '佚名（合成）'}
            </p>
            {/* key=entryRef：与 Reader 同一契约——切换 Entry 重挂载，
                正文管线不跨文章复用（ArticleContent 不响应 detail 换血）。 */}
            <ArticleContent key={selected.entryRef} detail={selected} />
          </div>
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto p-3" data-n360-management="">
          <p className="mb-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
            管理界面样本：订阅源表为合成数据；真实管理操作（刷新 / 编辑 /
            删除）在演示模式中没有入口。
          </p>
          <ul className="flex flex-col gap-2">
            {DEMO_SOURCES.map((source) => (
              <li
                key={source.id}
                data-n360-source={source.id}
                className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <p className="min-w-0 truncate text-sm font-medium text-[var(--lumi-text-primary)]">
                    {source.title}
                  </p>
                  <span className="shrink-0 text-xs tabular-nums text-[var(--lumi-text-tertiary)]">
                    {source.entryCount} 篇
                  </span>
                </div>
                <p className="mt-0.5 truncate text-xs text-[var(--lumi-text-tertiary)]">
                  {source.category} · {source.url} · 更新于 {source.lastRefreshedAt}
                </p>
                <div className="mt-2 flex gap-1.5" aria-hidden="true">
                  {['刷新', '编辑', '删除'].map((action) => (
                    <span
                      key={action}
                      className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1 text-xs text-[var(--lumi-text-disabled)]"
                    >
                      {action}（演示禁用）
                    </span>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export default ReadOnlyDemo
