/** DigestUsagePanel — N180 日报材料使用追踪（阅读器侧边）。
 *
 * 反查当前条目被「我的」哪些日报配置/期刊/栏目引用（服务端只在当前
 * 用户库上查询——其他用户的期刊天然不可见）。每条引用给出跳转链接
 * （打开设置的日报分类，citationAnchor 标注引用位置）。无引用 →
 * 诚实空态「还没有被日报引用」，不虚构。 */

import { Newspaper } from 'lucide-react'
import { useEntryDigestUsage } from '../api/queries'
import { requestOpenSettings } from './settings/settings-bridge'

export default function DigestUsagePanel({ entryRef }: { entryRef: string }) {
  const usage = useEntryDigestUsage(entryRef)
  if (usage.isPending || usage.isError) return null
  const items = usage.data.items

  return (
    <section
      className="mt-4 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3"
      data-testid="lumi-digest-usage-panel"
    >
      <div className="flex items-center gap-2">
        <Newspaper aria-hidden className="size-4 text-[var(--lumi-text-tertiary)]" />
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">日报使用</h3>
      </div>
      {items.length === 0 ? (
        <p className="mt-2 text-xs text-[var(--lumi-text-tertiary)]" data-testid="lumi-digest-usage-empty">
          还没有被日报引用过。
        </p>
      ) : (
        <ul className="mt-2 flex flex-col gap-1.5" data-testid="lumi-digest-usage-list">
          {items.map((item) => (
            <li
              key={`${item.configId}:${item.issueKey}:${item.sourceId}`}
              className="flex items-center gap-2 text-xs"
              data-testid="lumi-digest-usage-row"
            >
              <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-secondary)]">
                {item.configName} · {item.issueKey}
                {item.section ? <span className="ml-1 text-[var(--lumi-text-tertiary)]">（{item.section}）</span> : null}
              </span>
              <a
                href="#digest-usage"
                data-testid="lumi-digest-usage-jump"
                onClick={(event) => {
                  event.preventDefault()
                  requestOpenSettings('mail')
                }}
                className="shrink-0 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-accent-soft)] px-2 py-0.5 text-[11px] text-[var(--lumi-accent-text)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]"
                aria-label={`查看引用：${item.configName} ${item.issueKey} ${item.section}（${item.citationAnchor}）`}
                title={`引用位置 ${item.citationAnchor}`}
              >
                查看引用
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
