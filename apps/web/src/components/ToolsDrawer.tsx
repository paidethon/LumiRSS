/** ToolsDrawer — R11 方案 B：阅读工具唯一抽屉（R3 共享契约 §2/§4）。
 *
 * 桌面右侧 416px DetailDrawer / 移动端自动 ActionSheet 全宽底部面板
 * （形态切换由 DetailDrawer 原语承载，本组件不感知断点）。内部三个
 * 分组 tab（阅读 / 整理 / 共读，Tabs 原语键盘导航），组内是工具列表
 * （icon + 名称 + 一句说明）；点击进入面板内二级视图——返回栈在抽屉
 * 内（「返回工具列表」），禁止跳出不同尺寸的第二浮层。
 *
 * 工具承载（图2 九入口归属中抽屉内六项；全部复用既有面板组件，
 * 无占位假数据——每个工具都有真实后端或设备本地实现）：
 * - 阅读组：阅读预算（F014，会话内临时清单）、今日必读（N041，服务端
 *   持久化队列）、阅读路径（N050，设备本地）、阅读决策（NEW-221..230，
 *   服务端队列/计划）；
 * - 整理组：积压整理（F024，预览→确认→执行）；
 * - 共读组：共读空间（NEW-331..340，显式共享面）。
 *
 * 从面板内打开文章（预算清单/今日必读/阅读路径）= 离开抽屉回到正文
 * ——onOpenEntry 后整只抽屉关闭，让阅读区接管。面板自己的「关闭」
 * 按钮在抽屉语境下 = 返回工具列表（二级视图出栈）。 */

import { lazy, Suspense, useState } from 'react'
import {
  Archive,
  CalendarClock,
  ChevronLeft,
  Gauge,
  ListChecks,
  Route,
  Users,
  type LucideIcon,
} from 'lucide-react'
import type { BudgetCandidate } from '../lib/reading-budget'
import { DetailDrawer } from './ui/DetailDrawer'
import { Tabs } from './ui/Tabs'
import { cx } from './ui/cx'

// 各面板沿用 EntryList 的 bundle-guard 惯例：抽屉 chunk 打开时才拉取
// 对应面板实现；未进入二级视图的面板零请求、零挂载。
const ReadingBudgetPanel = lazy(() =>
  import('./ReadingBudgetPanel').then((m) => ({ default: m.ReadingBudgetPanel })),
)
const ReadingQueuePanel = lazy(() =>
  import('./ReadingQueuePanel').then((m) => ({ default: m.ReadingQueuePanel })),
)
const ReadingPathPanel = lazy(() =>
  import('./ReadingPathPanel').then((m) => ({ default: m.ReadingPathPanel })),
)
const ReadingDecisionsPanel = lazy(() =>
  import('./new2xx/ReadingDecisionsPanel').then((m) => ({ default: m.ReadingDecisionsPanel })),
)
const BacklogPanel = lazy(() => import('./BacklogPanel'))
const SpaceGovernanceTools = lazy(() =>
  import('./new331/SpaceGovernanceTools').then((m) => ({ default: m.SpaceGovernanceTools })),
)

/** 工具 id（分组 tab 内二级视图的路由键）。 */
type ToolId = 'budget' | 'queue' | 'path' | 'decisions' | 'backlog' | 'space'

/** 分组 tab 值。 */
type ToolsTab = 'reading' | 'organize' | 'coread'

interface ToolDef {
  id: ToolId
  label: string
  /** 一句说明（工具列表行副文案） */
  description: string
  icon: LucideIcon
  group: ToolsTab
}

/** 工具注册表：id / 分组 / 文案单一来源；顺序即列表展示序。 */
const TOOLS: readonly ToolDef[] = [
  {
    id: 'budget',
    label: '阅读预算',
    description: '按可用时间装填一份本会话的临时阅读清单',
    icon: Gauge,
    group: 'reading',
  },
  {
    id: 'queue',
    label: '今日必读',
    description: '服务端保存的每日阅读队列，可分段与排序',
    icon: CalendarClock,
    group: 'reading',
  },
  {
    id: 'path',
    label: '阅读路径',
    description: '本机的阅读足迹，可从最近读过的文章继续',
    icon: Route,
    group: 'reading',
  },
  {
    id: 'decisions',
    label: '阅读决策',
    description: '分时段安排待读、标记依赖与工作量',
    icon: ListChecks,
    group: 'reading',
  },
  {
    id: 'backlog',
    label: '积压整理',
    description: '预览后批量把旧文章标为已读（收藏与稍后读永不波及）',
    icon: Archive,
    group: 'organize',
  },
  {
    id: 'space',
    label: '共读空间',
    description: '与成员共享的阅读空间：讨论、审批与协作',
    icon: Users,
    group: 'coread',
  },
]

const TOOL_BY_ID = new Map(TOOLS.map((tool) => [tool.id, tool]))

const TAB_OPTIONS: ReadonlyArray<{ value: ToolsTab; label: string }> = [
  { value: 'reading', label: '阅读' },
  { value: 'organize', label: '整理' },
  { value: 'coread', label: '共读' },
]

export interface ToolsDrawerProps {
  open: boolean
  onClose: () => void
  /** 阅读预算装填候选（当前列表已加载 + 当前筛选下的未读） */
  budgetCandidates: BudgetCandidate[]
  /** 从工具面板内打开一篇文章（今日必读 / 阅读路径 / 预算清单）；
   * 打开后抽屉整体关闭，让正文接管。 */
  onOpenEntry?: (entryRef: string) => void
  /** 当前正在阅读的文章（今日必读「当前」标记用） */
  currentItemRef?: string | null
}

/** 工具列表行（44px 触控目标；icon + 名称 + 一句说明）。 */
function ToolRow({ tool, onOpen }: { tool: ToolDef; onOpen: () => void }) {
  const Icon = tool.icon
  return (
    <button
      type="button"
      data-testid={`tools-drawer-item-${tool.id}`}
      onClick={onOpen}
      className={cx(
        'flex min-h-11 w-full items-center gap-3 rounded-[var(--lumi-radius-md)] px-2.5 py-2 text-left',
        'transition-colors duration-[var(--lumi-motion-fast)]',
        'hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
      )}
    >
      <Icon aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />
      <span className="min-w-0">
        <span className="block text-sm font-medium text-[var(--lumi-text-primary)]">
          {tool.label}
        </span>
        <span className="block text-xs text-[var(--lumi-text-tertiary)]">
          {tool.description}
        </span>
      </span>
    </button>
  )
}

export default function ToolsDrawer({
  open,
  onClose,
  budgetCandidates,
  onOpenEntry,
  currentItemRef = null,
}: ToolsDrawerProps) {
  const [tab, setTab] = useState<ToolsTab>('reading')
  // 二级视图：null = 工具列表；否则为进入的工具（返回栈深度恒 1，
  // 面板内部不再下钻——契约禁止抽屉内再嵌套浮层/多级栈失控）。
  const [activeTool, setActiveTool] = useState<ToolId | null>(null)

  const closeDrawer = () => {
    onClose()
    // 关闭即复位二级视图：下次打开回到工具列表（可预期入口）。
    setActiveTool(null)
  }

  /** 面板内打开文章：交给宿主选中正文，同时收起抽屉。 */
  const openEntryFromTool = (entryRef: string) => {
    onOpenEntry?.(entryRef)
    closeDrawer()
  }

  const activeDef = activeTool !== null ? TOOL_BY_ID.get(activeTool) ?? null : null

  return (
    <DetailDrawer
      open={open}
      onClose={closeDrawer}
      title="工具"
      id="lumi-tools-drawer"
    >
      {activeDef !== null ? (
        /* 二级视图：返回 + 工具名 + 面板本体（返回栈在抽屉内） */
        <div data-testid="tools-drawer-secondary">
          <div className="mb-2 flex items-center gap-1">
            <button
              type="button"
              data-testid="tools-drawer-back"
              onClick={() => setActiveTool(null)}
              aria-label="返回工具列表"
              className={cx(
                'flex min-h-11 min-w-11 items-center justify-center rounded-[var(--lumi-radius-md)]',
                'text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)]',
                'hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
                'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
              )}
            >
              <ChevronLeft aria-hidden className="size-4" />
            </button>
            <span className="text-sm font-semibold text-[var(--lumi-text-primary)]">
              {activeDef.label}
            </span>
          </div>
          <Suspense fallback={null}>
            {activeDef.id === 'budget' && (
              <ReadingBudgetPanel
                candidates={budgetCandidates}
                onOpenEntry={openEntryFromTool}
                onClose={() => setActiveTool(null)}
              />
            )}
            {activeDef.id === 'queue' && (
              <ReadingQueuePanel
                currentItemRef={currentItemRef}
                onOpenEntry={openEntryFromTool}
                onClose={() => setActiveTool(null)}
              />
            )}
            {activeDef.id === 'path' && (
              <ReadingPathPanel
                onOpenEntry={openEntryFromTool}
                onClose={() => setActiveTool(null)}
              />
            )}
            {activeDef.id === 'decisions' && (
              <ReadingDecisionsPanel onClose={() => setActiveTool(null)} />
            )}
            {activeDef.id === 'backlog' && (
              <BacklogPanel onClose={() => setActiveTool(null)} />
            )}
            {activeDef.id === 'space' && <SpaceGovernanceTools />}
          </Suspense>
        </div>
      ) : (
        <Tabs<ToolsTab>
          aria-label="工具分组"
          value={tab}
          onValueChange={setTab}
          options={TAB_OPTIONS}
          panels={{
            reading: (
              <div className="flex flex-col gap-0.5">
                {TOOLS.filter((tool) => tool.group === 'reading').map((tool) => (
                  <ToolRow key={tool.id} tool={tool} onOpen={() => setActiveTool(tool.id)} />
                ))}
              </div>
            ),
            organize: (
              <div className="flex flex-col gap-0.5">
                {TOOLS.filter((tool) => tool.group === 'organize').map((tool) => (
                  <ToolRow key={tool.id} tool={tool} onOpen={() => setActiveTool(tool.id)} />
                ))}
              </div>
            ),
            coread: (
              <div className="flex flex-col gap-0.5">
                {TOOLS.filter((tool) => tool.group === 'coread').map((tool) => (
                  <ToolRow key={tool.id} tool={tool} onOpen={() => setActiveTool(tool.id)} />
                ))}
              </div>
            ),
          }}
        />
      )}
    </DetailDrawer>
  )
}
