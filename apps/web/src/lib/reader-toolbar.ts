/** Reader 工具栏动作注册表 — P07（用户可配置的阅读器工具栏）。
 *
 * 单一事实来源：ReaderHeader 工具栏上每个可配置动作的 id / 标签 /
 * 图标 / 默认次序 / 作用域 / 是否移动端常驻（primary）/ 是否锁定。
 * id 与既有按钮行为 1:1 对应——本模块只决定「排布与显隐」，不改变
 * 任何动作的语义；返回/来源导航与标题/作者/日期块不在注册表内
 * （恒展示，不可配置）。
 *
 * 存储格式（app-settings 的两个设备本地键，见 store/app-settings.ts）：
 * `string[]`，每项是一个动作 id 或其「隐藏占位」：
 * - `'id'`   → 该动作在此位置显示；
 * - `'-id'`  → 该动作被用户隐藏（占位记录）。隐藏必须占位而非缺席，
 *   否则 normalize 的「缺项补全」（为新增动作做的 forward-compat）
 *   会在下次加载时把用户刻意隐藏的动作复活。
 *
 * normalize（纯函数，可测试）：未知 id 丢弃、重复 id 去重（首个生效）、
 * 注册表新增而存储缺失的 id 按默认次序追加在末尾、锁定动作（收藏 /
 * 更多操作）强制可见、全隐藏 / 空数组 / 非数组 → 回退该断点默认序。
 *
 * 桌面与移动端默认序不同（都是既有视觉序的忠实快照）：
 * - 桌面：全部动作平铺在工具栏（0009 Gate 3 视觉序）；
 * - 移动端（O127）：primary 动作留工具栏，其余按既有收纳序折进
 *   「更多操作」菜单（查找/链接/AI/快照/朗读/分享/引用/打印）。 */

import type { LucideIcon } from 'lucide-react'
import {
  Camera,
  ExternalLink,
  Languages,
  Link2,
  MessageSquare,
  MoreHorizontal,
  Printer,
  Quote,
  Search,
  Share2,
  Star,
  Volume2,
} from 'lucide-react'

/** 工具栏配置作用的断点（两套键各自记忆，设备本地不同步）。 */
export type ReaderToolbarScope = 'desktop' | 'mobile'

/** 可配置动作 id（与既有按钮行为 1:1；不得改动各 id 的行为语义）。 */
export type ReaderToolbarActionId =
  | 'star'
  | 'open-original'
  | 'snapshot'
  | 'ai'
  | 'language'
  | 'find'
  | 'links'
  | 'speech'
  | 'share'
  | 'quote'
  | 'print'
  | 'more'

export interface ReaderToolbarActionDef {
  id: ReaderToolbarActionId
  /** 展示标签（自定义对话框 / 菜单语义；与既有按钮 aria-label 同源）。 */
  label: string
  icon: LucideIcon
  /** 桌面默认次序（1 起）= 0009 Gate 3 既有视觉序。 */
  defaultOrder: number
  /** 移动端默认次序（1 起）= O127 既有收纳序（primary 平铺序 + 菜单序）。 */
  mobileDefaultOrder: number
  /** 作用域：both = 两断点都提供；desktop / mobile = 仅其一（当前 12 个动作两断点都有）。 */
  scope: 'both' | 'desktop' | 'mobile'
  /** 移动端常驻工具栏（不折进「更多」菜单）——对应 O127 高频动作。 */
  primary: boolean
  /** 锁定：用户不可移除（收藏 / 更多操作）。 */
  locked: boolean
}

/** 动作注册表（顺序无关；次序由 defaultOrder / mobileDefaultOrder 表达）。 */
export const READER_TOOLBAR_ACTIONS: readonly ReaderToolbarActionDef[] = [
  {
    id: 'star',
    label: '收藏',
    icon: Star,
    defaultOrder: 1,
    mobileDefaultOrder: 1,
    scope: 'both',
    primary: true,
    locked: true,
  },
  {
    id: 'open-original',
    label: '打开原文',
    icon: ExternalLink,
    defaultOrder: 2,
    mobileDefaultOrder: 2,
    scope: 'both',
    primary: true,
    locked: false,
  },
  {
    id: 'snapshot',
    label: '保存快照',
    icon: Camera,
    defaultOrder: 3,
    mobileDefaultOrder: 7,
    scope: 'both',
    primary: false,
    locked: false,
  },
  {
    id: 'ai',
    label: 'AI 对话',
    icon: MessageSquare,
    defaultOrder: 4,
    mobileDefaultOrder: 6,
    scope: 'both',
    primary: false,
    locked: false,
  },
  {
    id: 'language',
    label: '语言视图',
    icon: Languages,
    defaultOrder: 5,
    mobileDefaultOrder: 3,
    scope: 'both',
    primary: true,
    locked: false,
  },
  {
    id: 'find',
    label: '文内查找',
    icon: Search,
    defaultOrder: 6,
    mobileDefaultOrder: 4,
    scope: 'both',
    primary: false,
    locked: false,
  },
  {
    id: 'links',
    label: '文中链接',
    icon: Link2,
    defaultOrder: 7,
    mobileDefaultOrder: 5,
    scope: 'both',
    primary: false,
    locked: false,
  },
  {
    id: 'speech',
    label: '朗读',
    icon: Volume2,
    defaultOrder: 8,
    mobileDefaultOrder: 8,
    scope: 'both',
    primary: false,
    locked: false,
  },
  {
    id: 'share',
    label: '分享',
    icon: Share2,
    defaultOrder: 9,
    mobileDefaultOrder: 9,
    scope: 'both',
    primary: false,
    locked: false,
  },
  {
    id: 'quote',
    label: '复制引用',
    icon: Quote,
    defaultOrder: 10,
    mobileDefaultOrder: 10,
    scope: 'both',
    primary: false,
    locked: false,
  },
  {
    id: 'print',
    label: '打印',
    icon: Printer,
    defaultOrder: 11,
    mobileDefaultOrder: 11,
    scope: 'both',
    primary: false,
    locked: false,
  },
  {
    id: 'more',
    label: '更多操作',
    icon: MoreHorizontal,
    defaultOrder: 12,
    mobileDefaultOrder: 12,
    scope: 'both',
    primary: true,
    locked: true,
  },
]

const REGISTRY_BY_ID: Record<ReaderToolbarActionId, ReaderToolbarActionDef> = Object.fromEntries(
  READER_TOOLBAR_ACTIONS.map((action) => [action.id, action]),
) as Record<ReaderToolbarActionId, ReaderToolbarActionDef>

/** 隐藏占位前缀（存储格式见文件头注释）。 */
const HIDDEN_PREFIX = '-'

export function readerToolbarAction(id: ReaderToolbarActionId): ReaderToolbarActionDef {
  return REGISTRY_BY_ID[id]
}

/** 该动作是否适用于断点（scope 过滤；当前全部 both，字段为前向兼容保留）。 */
function appliesToScope(id: ReaderToolbarActionId, scope: ReaderToolbarScope): boolean {
  const scopeOf = REGISTRY_BY_ID[id].scope
  return scopeOf === 'both' || scopeOf === scope
}

/** 断点默认序（registry 排序产物；返回新数组，调用方可自由改写）。 */
export function defaultReaderToolbarOrder(scope: ReaderToolbarScope): ReaderToolbarActionId[] {
  return READER_TOOLBAR_ACTIONS.filter((action) => appliesToScope(action.id, scope))
    .sort((a, b) =>
      scope === 'desktop'
        ? a.defaultOrder - b.defaultOrder
        : a.mobileDefaultOrder - b.mobileDefaultOrder,
    )
    .map((action) => action.id)
}

/** 解析单个存储项：`'id'` → 可见；`'-id'` → 隐藏占位；未知 / 非法 → null。 */
export function parseReaderToolbarEntry(
  entry: unknown,
): { id: ReaderToolbarActionId; visible: boolean } | null {
  if (typeof entry !== 'string') return null
  const trimmed = entry.trim()
  if (trimmed === '') return null
  const visible = !trimmed.startsWith(HIDDEN_PREFIX)
  const base = visible ? trimmed : trimmed.slice(HIDDEN_PREFIX.length)
  if (!(base in REGISTRY_BY_ID)) return null
  return { id: base as ReaderToolbarActionId, visible }
}

/**
 * 归一化任意（不可信的）持久化数组为该断点的合法存储形式（`string[]`：
 * 可见段 `'id'` + 隐藏占位段 `'-id'`）：
 * - 非数组 / 空 / 全部非法或全隐藏 → 该断点默认序（至少一个动作可见）；
 * - 未知 id 丢弃；重复 id 去重（首次出现生效）；
 * - 锁定动作（收藏 / 更多操作）强制可见——不可被移除；
 * - 注册表有而存储缺失的 id（新版本新增动作）按默认次序追加在可见段末尾；
 * - 隐藏动作以 `'-id'` 占位追加在末尾（防缺项补全复活用户选择）。
 */
export function normalizeReaderToolbarOrder(raw: unknown, scope: ReaderToolbarScope): string[] {
  const defaults = defaultReaderToolbarOrder(scope)
  if (!Array.isArray(raw)) return defaults
  const seen = new Set<ReaderToolbarActionId>()
  const visible: ReaderToolbarActionId[] = []
  const hidden: ReaderToolbarActionId[] = []
  for (const entry of raw) {
    const parsed = parseReaderToolbarEntry(entry)
    if (parsed === null || !appliesToScope(parsed.id, scope) || seen.has(parsed.id)) continue
    seen.add(parsed.id)
    if (parsed.visible || REGISTRY_BY_ID[parsed.id].locked) visible.push(parsed.id)
    else hidden.push(parsed.id)
  }
  // 缺项补全：存储里没提到的 id（升级新增的动作）按默认次序接在后面
  for (const id of defaults) {
    if (!seen.has(id)) visible.push(id)
  }
  // 守卫：至少一个动作可见（不可达的纯防御——锁定动作恒可见）
  if (visible.length === 0) return defaults
  return [...visible, ...hidden.map((id) => `${HIDDEN_PREFIX}${id}`)]
}

/** 渲染侧解析：给定（已归一化的）存储数组，返回该断点实际可见的动作 id 序列。 */
export function resolveReaderToolbarVisible(
  order: unknown,
  scope: ReaderToolbarScope,
): ReaderToolbarActionId[] {
  return normalizeReaderToolbarOrder(order, scope).flatMap((entry) => {
    const parsed = parseReaderToolbarEntry(entry)
    return parsed !== null && parsed.visible ? [parsed.id] : []
  })
}
