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
export type CommandSection = '导航' | '视图' | '外观' | '来源' | '保存的视图' | '当前页'

export interface Command {
  id: string
  title: string
  section: CommandSection
  /** 额外匹配词（英文别名/拼音缩写等；casefold includes 匹配）。 */
  keywords?: string
  run: () => void
  /** F120：权限/可用性门——false 的命令不出现在面板（负向：privacy/
   * demo 或禁用态动作隐藏）。 */
  available?: boolean
}

/** 构建命令所需的当前状态快照（组件层从 store 读取后传入）。 */
export interface CommandContext {
  section: AppSection
  view: UiView
  themeMode: AppSettings['themeMode']
  glassEffect: AppSettings['glassEffect']
  listDensity: AppSettings['listDensity']
  listTimeFormat: AppSettings['listTimeFormat']
  /** F120：能力开关（无权限动作不装配）。 */
  capabilities?: {
    /** 演示隐私开启时：导出/朗读等会泄露内容的动作隐藏。 */
    privacyDemoOn?: boolean
    speechEnabled?: boolean
    quizEnabled?: boolean
    searchExportEnabled?: boolean
  }
  /** F120：数据源扩展（组件层查询后注入）。 */
  subscriptions?: Array<{ id: string; title: string; open: () => void }>
  savedViews?: Array<{ id: string; title: string; open: () => void }>
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
  { section: 'sources', title: '打开来源', keywords: 'sources 来源 registry 注册表' },
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
  if (q === '') return commands.filter((command) => command.available !== false)
  return commands.filter(
    (command) =>
      command.available !== false &&
      (command.title.toLowerCase().includes(q) ||
        (command.keywords !== undefined && command.keywords.toLowerCase().includes(q))),
  )
}

/** F120：模糊匹配打分（子序列；连续命中 > 分隔命中；中文按字）。
 * 返回 null = 不匹配；否则返回分数（越大越好）。同分按原始顺序稳定。 */
export function fuzzyCommandScore(text: string, query: string): number | null {
  const haystack = [...text.toLowerCase()]
  const needle = [...query.trim().toLowerCase()]
  if (needle.length === 0) return 0
  if (needle.length > haystack.length) return null
  let score = 0
  let hi = 0
  let lastHit = -1
  for (let ni = 0; ni < needle.length; ni += 1) {
    const char = needle[ni] as string
    let found = -1
    while (hi < haystack.length) {
      if (haystack[hi] === char) {
        found = hi
        hi += 1
        break
      }
      hi += 1
    }
    if (found === -1) return null // 子序列断裂 → 不匹配
    if (lastHit >= 0 && found === lastHit + 1) score += 3 // 连续命中加权
    else if (lastHit >= 0) score += 1 // 分隔命中
    if (found === 0) score += 2 // 前缀额外加分
    lastHit = found
  }
  return score
}

/** F120：按模糊分排序的过滤（无查询 = 全部可用命令，保持原顺序）。 */
export function filterCommandsFuzzy(commands: Command[], query: string): Command[] {
  const available = commands.filter((command) => command.available !== false)
  const q = query.trim()
  if (q === '') return available
  const scored: Array<{ command: Command; score: number }> = []
  for (const command of available) {
    const titleScore = fuzzyCommandScore(command.title, q)
    const keywordScore =
      command.keywords !== undefined ? fuzzyCommandScore(command.keywords, q) : null
    const best =
      titleScore !== null && keywordScore !== null
        ? Math.max(titleScore, keywordScore)
        : (titleScore ?? keywordScore)
    if (best !== null) scored.push({ command, score: best })
  }
  return scored
    .sort((a, b) => b.score - a.score)
    .map((item) => item.command)
}

/** F120：上下文动作（随 section 变化）。
 * 阅读器内（home + 打开文章）→ 导出/朗读/自测；搜索页 → 导出清单。
 * 无对应上下文 → 空数组。能力关闭/privacy demo → 不装配（负向隐藏）。 */
export function buildContextCommands(
  context: CommandContext,
  actions: {
    exportReader?: () => void
    speakReader?: () => void
    quizReader?: () => void
    exportSearchList?: () => void
  },
): Command[] {
  const commands: Command[] = []
  const caps = context.capabilities ?? {}
  if (context.section === 'home') {
    if (caps.privacyDemoOn !== true) {
      if (actions.exportReader !== undefined) {
        commands.push({
          id: 'ctx-reader-export',
          title: '导出当前文章',
          section: '当前页',
          keywords: 'export 文章 导出',
          run: actions.exportReader,
        })
      }
      if (caps.speechEnabled !== false && actions.speakReader !== undefined) {
        commands.push({
          id: 'ctx-reader-speech',
          title: '朗读当前文章',
          section: '当前页',
          keywords: 'speech 朗读 tts',
          run: actions.speakReader,
        })
      }
      if (caps.quizEnabled !== false && actions.quizReader !== undefined) {
        commands.push({
          id: 'ctx-reader-quiz',
          title: '自测当前文章',
          section: '当前页',
          keywords: 'quiz 自测 测验',
          run: actions.quizReader,
        })
      }
    }
  }
  if (context.section === 'search' && caps.privacyDemoOn !== true) {
    if (caps.searchExportEnabled !== false && actions.exportSearchList !== undefined) {
      commands.push({
        id: 'ctx-search-export',
        title: '导出搜索结果清单',
        section: '当前页',
        keywords: 'export 搜索 导出 清单',
        run: actions.exportSearchList,
      })
    }
  }
  return commands
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

  // ---- F120：数据源扩展（订阅来源 / 保存视图；组件层注入） ----
  for (const subscription of context.subscriptions ?? []) {
    commands.push({
      id: `source-${subscription.id}`,
      title: `打开订阅：${subscription.title}`,
      section: '来源',
      keywords: 'subscription 订阅 source',
      run: subscription.open,
    })
  }
  for (const view of context.savedViews ?? []) {
    commands.push({
      id: `saved-view-${view.id}`,
      title: `保存的视图：${view.title}`,
      section: '保存的视图',
      keywords: 'view 保存 视图',
      run: view.open,
    })
  }

  return commands
}
