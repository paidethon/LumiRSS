/** nav-registry — 导航入口唯一真源（R3 共享契约 §3，Wave0 foundation）。
 *
 * 收敛此前三处硬编码入口表：Sidebar.tsx（桌面侧栏行）、
 * MobileTabBar.tsx（底部导航岛四 tab）、SourcesPage.tsx TYPE_ORDER
 * （来源中心分组顺序）。消费方只读注册表渲染，入口数据不再各自硬编码；
 * 渲染层（行样式、特殊行如 RSS 分类树）仍留在各组件。
 *
 * id 约定：
 * - AppSection 字面量        → section 导航（selectSection）；
 * - `home:${UiView}`         → home 段内的视图入口（稍后读/收藏），
 *                              导航 = section home + ALL_SCOPE + 该 view；
 * - `source:${SourceType}`   → 内容来源入口（当前仅 RSS 订阅——scope
 *                              直达；其余八类中的 section 类直接用
 *                              AppSection id）；
 * - `settings:${category}`   → 设置深链（settings-bridge 事件，契约 §3：
 *                              「深链设置仍走 settings-bridge 事件，但
 *                              入口定义在注册表」）。
 *
 * AppSection 语义归 reader-ui store 所有，本文件不复制其定义（App.tsx
 * 与 store 不动）；countKey 为未来计数徽标预留（契约 §3），当前无消费方，
 * 全部缺省。 */

import {
  Archive,
  Bookmark,
  Bot,
  Clock,
  FileText,
  FolderOpen,
  Globe,
  Inbox,
  Layers,
  Link2,
  Mail,
  Rss,
  Search,
  Star,
  Tags,
  Zap,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { AppSection } from '../store/reader-ui'
import { ALL_SCOPE } from '../store/reader-ui'
import type { UiView } from './read-later'
import type { ContentScope } from './navigation'

/** 来源类型（契约 §3 全集；rsshub 无侧栏入口，仅来源中心分组用）。 */
export type SourceTypeKind =
  | 'rss'
  | 'rsshub'
  | 'bookmark'
  | 'clip'
  | 'snapshot'
  | 'inbox'
  | 'api_source'
  | 'newsletter'
  | 'obsidian'

/** 入口 id（见文件头约定）。 */
export type NavEntryId = AppSection | `home:${UiView}` | `source:${SourceTypeKind}` | `settings:${string}`

/** 入口出现的表面。 */
export type NavSurface = 'sidebar' | 'tabbar'

/** 侧栏分组（order 排版：阅读类 → 内容来源类 → 工具类）。 */
export type NavGroup = 'reading' | 'sources' | 'tools'

export interface NavEntry {
  id: NavEntryId
  kind: 'section' | 'settings'
  label: string
  icon: LucideIcon
  order: number
  group: NavGroup
  /** 来源类型（契约 §3：来源中心八类与侧栏内容入口同源） */
  sourceType?: SourceTypeKind
  /** 计数徽标键（预留，当前无消费方） */
  countKey?: string
  /** home 段视图入口叠加的 view（缺省不动 view） */
  view?: UiView
  /** scope 入口叠加的范围（缺省不动 scope） */
  scope?: ContentScope
  /** 出现在哪些表面 */
  surfaces: NavSurface[]
  /** 底栏紧凑标签（tabbar 表面必填） */
  shortLabel?: string
}

/** 侧栏分组标题。 */
export const NAV_GROUP_LABELS: Record<NavGroup, string> = {
  reading: '阅读',
  sources: '内容来源',
  tools: '工具',
}

/** 导航入口唯一真源（按 order 升序阅读：阅读 → 内容来源 → 工具）。 */
export const NAV_ENTRIES: NavEntry[] = [
  // ===== 阅读类 =====
  {
    id: 'home',
    kind: 'section',
    label: '全部信息源',
    icon: Inbox,
    order: 10,
    group: 'reading',
    view: 'all',
    scope: ALL_SCOPE,
    surfaces: ['sidebar', 'tabbar'],
    shortLabel: '首页',
  },
  {
    id: 'home:read-later',
    kind: 'section',
    label: '稍后读',
    icon: Clock,
    order: 11,
    group: 'reading',
    view: 'read-later',
    scope: ALL_SCOPE,
    surfaces: ['sidebar'],
  },
  {
    id: 'home:starred',
    kind: 'section',
    label: '收藏',
    icon: Star,
    order: 12,
    group: 'reading',
    view: 'starred',
    scope: ALL_SCOPE,
    surfaces: ['sidebar'],
  },
  // ===== 内容来源类（八类 sourceType 与来源中心同源）=====
  {
    id: 'source:rss',
    kind: 'section',
    label: 'RSS 订阅',
    icon: Rss,
    order: 20,
    group: 'sources',
    sourceType: 'rss',
    view: 'all',
    scope: { kind: 'rss' },
    surfaces: ['sidebar'],
  },
  {
    id: 'sources',
    kind: 'section',
    label: '来源',
    icon: Layers,
    order: 21,
    group: 'sources',
    surfaces: ['sidebar', 'tabbar'],
    shortLabel: '来源',
  },
  {
    id: 'bookmarks',
    kind: 'section',
    label: '书签',
    icon: Bookmark,
    order: 22,
    group: 'sources',
    sourceType: 'bookmark',
    surfaces: ['sidebar'],
  },
  {
    id: 'clips',
    kind: 'section',
    label: '网页剪藏',
    icon: Globe,
    order: 23,
    group: 'sources',
    sourceType: 'clip',
    surfaces: ['sidebar'],
  },
  {
    id: 'snapshots',
    kind: 'section',
    label: '网页快照',
    icon: Link2,
    order: 24,
    group: 'sources',
    sourceType: 'snapshot',
    surfaces: ['sidebar'],
  },
  {
    id: 'inbox',
    kind: 'section',
    label: '收件箱',
    icon: Archive,
    order: 25,
    group: 'sources',
    sourceType: 'inbox',
    surfaces: ['sidebar'],
  },
  {
    id: 'settings:api-sources',
    kind: 'settings',
    label: 'API 来源',
    icon: FileText,
    order: 26,
    group: 'sources',
    sourceType: 'api_source',
    surfaces: ['sidebar'],
  },
  {
    id: 'settings:mail',
    kind: 'settings',
    label: '邮件简报',
    icon: Mail,
    order: 27,
    group: 'sources',
    sourceType: 'newsletter',
    surfaces: ['sidebar'],
  },
  {
    id: 'obsidian',
    kind: 'section',
    label: 'Obsidian 库',
    icon: FileText,
    order: 28,
    group: 'sources',
    sourceType: 'obsidian',
    surfaces: ['sidebar'],
  },
  // ===== 工具类 =====
  {
    id: 'search',
    kind: 'section',
    label: '搜索',
    icon: Search,
    order: 30,
    group: 'tools',
    surfaces: ['sidebar', 'tabbar'],
    shortLabel: '搜索',
  },
  {
    id: 'workspaces',
    kind: 'section',
    label: '工作区',
    icon: FolderOpen,
    order: 31,
    group: 'tools',
    surfaces: ['sidebar'],
  },
  {
    id: 'agent',
    kind: 'section',
    label: 'Agent 工作台',
    icon: Bot,
    order: 32,
    group: 'tools',
    surfaces: ['sidebar'],
  },
  {
    id: 'settings:ai',
    kind: 'settings',
    label: 'RAG 索引',
    icon: Zap,
    order: 33,
    group: 'tools',
    surfaces: ['sidebar'],
  },
  {
    id: 'graph',
    kind: 'section',
    label: '标签 / 图谱',
    icon: Tags,
    order: 34,
    group: 'tools',
    surfaces: ['sidebar'],
  },
  {
    id: 'favorites',
    kind: 'section',
    label: '收藏',
    icon: Star,
    order: 35,
    group: 'tools',
    surfaces: ['tabbar'],
    shortLabel: '收藏',
  },
]

/** 导航目标（渲染层据此 dispatch；字段缺省 = 不动对应维度）。 */
export interface NavTarget {
  section: AppSection
  scope?: ContentScope
  view?: UiView
}

const SETTINGS_PREFIX = 'settings:'

/** settings 深链入口的分类 id；非 settings 入口返回 null。 */
export function settingsCategoryOf(id: NavEntryId): string | null {
  return id.startsWith(SETTINGS_PREFIX) ? id.slice(SETTINGS_PREFIX.length) : null
}

/** 入口 → 导航目标：section 入口给出 (section, scope?, view?)；settings
 * 入口只有 settingsCategory（经 requestOpenSettings 派发）。复合 id
 * （`home:*` / `source:*`）都落在 home 段。 */
export function navTargetOf(entry: NavEntry): NavTarget {
  const category = settingsCategoryOf(entry.id)
  if (entry.kind === 'settings' || category !== null) {
    return { section: 'home' }
  }
  const head = entry.id.split(':')[0]
  const section: AppSection =
    head === 'home' || head === 'source' ? 'home' : (entry.id as AppSection)
  return { section, scope: entry.scope, view: entry.view }
}

/** 指定表面的入口（order 升序）。 */
export function navEntriesForSurface(surface: NavSurface): NavEntry[] {
  return NAV_ENTRIES.filter((entry) => entry.surfaces.includes(surface)).sort(
    (a, b) => a.order - b.order,
  )
}

/** 侧栏分组渲染模型（组序 reading → sources → tools，组内 order 升序）。 */
export function navGroupsForSidebar(): Array<{
  group: NavGroup
  label: string
  entries: NavEntry[]
}> {
  const groups: NavGroup[] = ['reading', 'sources', 'tools']
  return groups.map((group) => ({
    group,
    label: NAV_GROUP_LABELS[group],
    entries: navEntriesForSurface('sidebar').filter((entry) => entry.group === group),
  }))
}

/** 来源中心分组顺序（SourcesPage TYPE_ORDER 的注册表化供源）。
 *
 * 前六位保持 SourcesPage 现行顺序与文案（rss/rsshub/api_source/
 * newsletter/inbox/obsidian——含「邮件桥」这一来源中心语境标签），使其
 * 未来直接替换本地 TYPE_ORDER 时渲染零漂移；bookmark/clip/snapshot 为
 * 八类补齐。manage 动作留在 SourcesPage（依赖页内 AddSourceDialog
 * 上下文，不进注册表）。 */
export function sourceTypeSourceOrder(): Array<{ type: SourceTypeKind; label: string }> {
  return [
    { type: 'rss', label: 'RSS 订阅' },
    { type: 'rsshub', label: 'RSSHub 路由' },
    { type: 'api_source', label: 'API 来源' },
    { type: 'newsletter', label: '邮件桥' },
    { type: 'inbox', label: '收件箱' },
    { type: 'obsidian', label: 'Obsidian' },
    { type: 'bookmark', label: '书签' },
    { type: 'clip', label: '网页剪藏' },
    { type: 'snapshot', label: '网页快照' },
  ]
}
