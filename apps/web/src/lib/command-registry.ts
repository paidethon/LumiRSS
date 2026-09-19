/** command-registry — F30 命令面板的命令注册/过滤纯逻辑。
 *
 * 设计约束：全部命令复用既有 action（selectSection / selectView /
 * settings.update / goBack），本模块不复制任何业务逻辑——只做
 * 「当前状态 + 动作集合 → Command[]」的装配与关键词过滤（casefold
 * includes，title + keywords 双字段）。组件层（CommandPalette）持有
 * store 与动作引用，经 buildCommands 注入。
 *
 * Command 结构刻意保持数据化（id/title/section/keywords/run），测试
 * 无需渲染组件即可断言过滤语义。 */

import type { AppSection } from '../store/reader-ui'
import type { UiView } from '../lib/read-later'
import type { AppSettings } from '../store/app-settings'

/** 命令分组标题（面板内小字展示 + 排序依据）。 */
export type CommandSection = '导航' | '视图' | '外观'

export interface Command {
  id: string
  title: string
  section: CommandSection
  /** 额外匹配词（英文别名/拼音缩写等；casefold includes 匹配）。 */
  keywords?: string
  run: () => void
}

/** 构建命令所需的当前状态快照（组件层从 store 读取后传入）。 */
export interface CommandContext {
  section: AppSection
  view: UiView
  themeMode: AppSettings['themeMode']
  glassEffect: AppSettings['glassEffect']
  listDensity: AppSettings['listDensity']
  listTimeFormat: AppSettings['listTimeFormat']
}

/** 既有动作的注入口（全部来自 store/hook，本模块不实现动作本身）。 */
export interface CommandActions {
  selectSection: (section: AppSection) => void
  selectView: (view: UiView) => void
  updateSettings: (patch: Partial<AppSettings>) => void
  /** 统一返回语义（lib/nav-history.goBack）。 */
  goBack: () => void
}

/** 一级页面导航命令（与 store/reader-ui AppSection 全集一一对应）。 */
const SECTION_COMMANDS: Array<{ section: AppSection; title: string; keywords: string }> = [
  { section: 'home', title: '打开首页', keywords: 'home 时间线 entries' },
  { section: 'subscriptions', title: '打开订阅管理', keywords: 'subscriptions feeds 订阅源' },
  { section: 'search', title: '打开搜索', keywords: 'search 搜索' },
  { section: 'favorites', title: '打开收藏', keywords: 'favorites star 收藏' },
  { section: 'bookmarks', title: '打开书签', keywords: 'bookmarks 书签' },
  { section: 'workspaces', title: '打开工作区', keywords: 'workspaces 工作区' },
  { section: 'clips', title: '打开剪藏', keywords: 'clips 剪藏' },
  { section: 'snapshots', title: '打开快照', keywords: 'snapshots 快照' },
  { section: 'inbox', title: '打开收件箱', keywords: 'inbox 收件箱' },
  { section: 'obsidian', title: '打开 Obsidian 库', keywords: 'obsidian 笔记 vault' },
  { section: 'agent', title: '打开 Agent 工作台', keywords: 'agent ai 工作台' },
  { section: 'graph', title: '打开图谱', keywords: 'graph 关系 图谱' },
]

const VIEW_COMMANDS: Array<{ view: UiView; title: string; keywords: string }> = [
  { view: 'all', title: '视图：全部文章', keywords: 'all 全部' },
  { view: 'unread', title: '视图：未读', keywords: 'unread 未读' },
  { view: 'starred', title: '视图：收藏', keywords: 'starred 收藏' },
  { view: 'read-later', title: '视图：稍后读', keywords: 'read later 稍后读' },
]

/** casefold includes：title + keywords 任一命中即保留。空查询返回全部。 */
export function filterCommands(commands: Command[], query: string): Command[] {
  const q = query.trim().toLowerCase()
  if (q === '') return commands
  return commands.filter(
    (command) =>
      command.title.toLowerCase().includes(q) ||
      (command.keywords !== undefined && command.keywords.toLowerCase().includes(q)),
  )
}

/** 装配命令全集（顺序：导航 → 返回 → 视图 → 外观；面板按数组顺序渲染）。 */
export function buildCommands(context: CommandContext, actions: CommandActions): Command[] {
  const commands: Command[] = []

  for (const entry of SECTION_COMMANDS) {
    commands.push({
      id: `nav-${entry.section}`,
      title: entry.title,
      section: '导航',
      keywords: entry.keywords,
      run: () => actions.selectSection(entry.section),
    })
  }

  commands.push({
    id: 'nav-back',
    title: '返回上一页',
    section: '导航',
    keywords: 'back go back 返回',
    run: () => actions.goBack(),
  })

  for (const entry of VIEW_COMMANDS) {
    commands.push({
      id: `view-${entry.view}`,
      title: entry.view === context.view ? `${entry.title}（当前）` : entry.title,
      section: '视图',
      keywords: entry.keywords,
      run: () => actions.selectView(entry.view),
    })
  }

  // ---- 外观（settings.update 既有通道；当前值以「（当前）」后缀诚实标注） ----
  const markCurrent = (title: string, isCurrent: boolean): string =>
    isCurrent ? `${title}（当前）` : title

  const themeCommands: Array<{ value: AppSettings['themeMode']; title: string; keywords: string }> = [
    { value: 'light', title: '外观：浅色主题', keywords: 'theme light 浅色 亮色' },
    { value: 'dark', title: '外观：深色主题', keywords: 'theme dark 深色 暗色' },
    { value: 'system', title: '外观：跟随系统主题', keywords: 'theme system 跟随系统' },
  ]
  for (const entry of themeCommands) {
    commands.push({
      id: `theme-${entry.value}`,
      title: markCurrent(entry.title, context.themeMode === entry.value),
      section: '外观',
      keywords: entry.keywords,
      run: () => actions.updateSettings({ themeMode: entry.value }),
    })
  }

  const glassCommands: Array<{ value: AppSettings['glassEffect']; title: string; keywords: string }> = [
    { value: 'on', title: '玻璃效果：开启', keywords: 'glass on 玻璃 开' },
    { value: 'off', title: '玻璃效果：关闭', keywords: 'glass off 玻璃 关' },
    { value: 'auto', title: '玻璃效果：跟随系统', keywords: 'glass auto 玻璃 自动' },
  ]
  for (const entry of glassCommands) {
    commands.push({
      id: `glass-${entry.value}`,
      title: markCurrent(entry.title, context.glassEffect === entry.value),
      section: '外观',
      keywords: entry.keywords,
      run: () => actions.updateSettings({ glassEffect: entry.value }),
    })
  }

  const densityCommands: Array<{ value: AppSettings['listDensity']; title: string; keywords: string }> = [
    { value: 'compact', title: '列表密度：紧凑', keywords: 'density compact 紧凑' },
    { value: 'standard', title: '列表密度：标准', keywords: 'density standard 标准' },
    { value: 'comfortable', title: '列表密度：宽松', keywords: 'density comfortable 宽松' },
  ]
  for (const entry of densityCommands) {
    commands.push({
      id: `density-${entry.value}`,
      title: markCurrent(entry.title, context.listDensity === entry.value),
      section: '外观',
      keywords: entry.keywords,
      run: () => actions.updateSettings({ listDensity: entry.value }),
    })
  }

  const timeCommands: Array<{ value: AppSettings['listTimeFormat']; title: string; keywords: string }> = [
    { value: 'relative', title: '时间格式：相对时间', keywords: 'time relative 相对' },
    { value: 'absolute', title: '时间格式：绝对时间', keywords: 'time absolute 绝对' },
  ]
  for (const entry of timeCommands) {
    commands.push({
      id: `time-${entry.value}`,
      title: markCurrent(entry.title, context.listTimeFormat === entry.value),
      section: '外观',
      keywords: entry.keywords,
      run: () => actions.updateSettings({ listTimeFormat: entry.value }),
    })
  }

  return commands
}
