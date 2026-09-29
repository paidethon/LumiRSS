/** NEW-221..230 阅读决策面板 —— 队列和阅读计划的用户决策工具区。
 *
 * 十组能力，每组成一个真实可用的 section（NEW 文件各自维护，见
 * sections-*.tsx）：
 *
 * - NEW-221 分时段阅读队列（打开接续 / 用户显式顺延）
 * - NEW-222 队列依赖关系（未满足前置提示，绝不阻止跳读）
 * - NEW-223 队列工作量预览（本人速度估算，压缩范围用户挑）
 * - NEW-224 阅读预约清单（一次性、应用内、可改期/取消）
 * - NEW-225 积压处理向导（抽样预览→keep/归档两段式/分批，绝不默认全读）
 * - NEW-226 队列容量上限（满员进待确认区，用户裁决替换/暂不加入）
 * - NEW-227 章节级阅读计划（完成按章节记账，不是文章百分比）
 * - NEW-228 阅读中断便签（下次从哪继续+在想什么，读完归档）
 * - NEW-229 阅读约定卡（双方独立确认；对方状态诚实不可见）
 * - NEW-230 队列重复主题提醒（自选主题集中度，调换位置手动）
 */

import { useState } from 'react'
import { cx } from '../ui/cx'
import { CapacitySection } from './sections-capacity'
import { NotesSection } from './sections-notes'
import { PlanSection } from './sections-plan'
import { PrereqSection } from './sections-prereq'
import { ReminderSection } from './sections-reminder'
import { SlotSection } from './sections-slot'
import { TopicSection } from './sections-topic'
import { WizardSection } from './sections-wizard'
import { WorkloadSection } from './sections-workload'
import { PactSection } from './sections-pact'

const TABS = [
  { key: 'slots', label: '分时段' },
  { key: 'prereqs', label: '依赖' },
  { key: 'workload', label: '工作量' },
  { key: 'reminders', label: '预约' },
  { key: 'wizard', label: '积压向导' },
  { key: 'capacity', label: '容量' },
  { key: 'plan', label: '章节计划' },
  { key: 'notes', label: '中断便签' },
  { key: 'pacts', label: '约定卡' },
  { key: 'topics', label: '主题' },
] as const

type TabKey = (typeof TABS)[number]['key']

export function ReadingDecisionsPanel({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<TabKey>('slots')
  return (
    <div
      className="flex h-full min-h-0 flex-col gap-3 border-b border-[var(--lumi-separator)] bg-[var(--lumi-surface)] px-4 py-3"
      aria-label="阅读决策"
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-[var(--lumi-text-primary)]">
          阅读决策
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="关闭阅读决策面板"
          className="min-h-11 min-w-11 rounded-[var(--lumi-radius-md)] px-2 text-xs text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-text-secondary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        >
          关闭
        </button>
      </div>
      <div role="tablist" aria-label="阅读决策分组" className="flex flex-wrap gap-1">
        {TABS.map((entry) => (
          <button
            key={entry.key}
            type="button"
            role="tab"
            aria-selected={tab === entry.key}
            onClick={() => setTab(entry.key)}
            className={cx(
              'min-h-7 rounded-[var(--lumi-radius-full)] px-2.5 py-1 text-xs transition-colors duration-[var(--lumi-motion-fast)]',
              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
              tab === entry.key
                ? 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]'
                : 'text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-text-secondary)]',
            )}
          >
            {entry.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        {tab === 'slots' && <SlotSection />}
        {tab === 'prereqs' && <PrereqSection />}
        {tab === 'workload' && <WorkloadSection />}
        {tab === 'reminders' && <ReminderSection />}
        {tab === 'wizard' && <WizardSection />}
        {tab === 'capacity' && <CapacitySection />}
        {tab === 'plan' && <PlanSection />}
        {tab === 'notes' && <NotesSection />}
        {tab === 'pacts' && <PactSection />}
        {tab === 'topics' && <TopicSection />}
      </div>
    </div>
  )
}
