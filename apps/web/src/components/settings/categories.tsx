/** 设置分类共享模块 — 0010a Gate E。
 *
 * E1（AC5）：分类内容与分类定义从 SettingsModal 抽出，桌面 Modal 与
 * 移动 MobileSettingsScreen 共享同一组数据/组件（Folo 的共享方式：
 * 数据层与分类页共享，外壳各自实现）。
 *
 * 信息架构（本次控制面整理）：「备份与恢复」并入「数据控制」——
 * 缓存 / 设置 / 配置迁移 / 完整备份 / 备份历史 / WebDAV / 恢复同页管理。
 * RSSHub 分类只保留真实控制面（浏览器侧参考清单假控制已退役）。 */

import { useQueryClient } from '@tanstack/react-query'
import {
  BookOpenText,
  Bot,
  Database,
  ExternalLink,
  FileText,
  Filter,
  Info,
  Keyboard,
  Languages,
  LayoutGrid,
  Palette,
  Rss,
  Satellite,
  Settings2,
  Sparkles,
  UserCog,
} from 'lucide-react'
import { useAppSettings } from '../../store/app-settings'
import type {
  ReaderFontFamily,
  ReaderImageMode,
  UiFontStack,
  UiFontSize,
} from '../../store/app-settings'
import type { ThemeMode } from '../../lib/theme'
import { SHORTCUTS } from '../../lib/keyboard-shortcuts'
import type { SettingItemDef } from './SettingItem'
import {
  AccentColorPicker,
  CustomCssEditor,
  ReaderBackgroundPicker,
  ReaderPresetPicker,
} from './AppearanceControls'
import { FilterRulesSection } from './FilterRulesPage'
import { RssHubControlCenter } from './RssHubControlCenter'
import { OperationsSettingsSection } from './OperationsSettingsSection'
// 数据控制（原「备份与恢复」并入）：配置迁移 + 完整备份 + 历史 + WebDAV
import { DataBackupSection } from './DataControlPage'
// AI 设置（Profile + 用途分配 + 服务端密钥，真实可用）
import { AiSettingsSection } from './AiSettingsPage'
// 0013 Gate 4：订阅与来源（OPML 导入导出 + FreshRSS 状态/高级入口）
import { SourcesSettingsSection } from './SourcesSettingsSection'
// 0012：深度阅读设置（字体管理 / 中文排版 / 代码高亮 / 主题包）
import { ReaderFontManager } from './reader/ReaderFontManager'
import {
  ChineseTypographySettings,
  CodeHighlightSettings,
  ReaderThemePackSettings,
} from './reader/ReaderDeepControls'
// 0017：连续排版 Slider + 恢复默认（设置 → 阅读）
import { ReaderTypographyControls } from './reader/ReaderTypographyControls'
// 关于页：Web/BFF 构建溯源（版本错配诊断）
import { AboutVersion } from './AboutVersion'

// ---- 分类定义 ----

export type CategoryId =
  | 'general'
  | 'appearance'
  | 'reading'
  | 'shortcuts'
  | 'translation'
  | 'filters'
  | 'rsshub'
  | 'sources'
  | 'ai'
  | 'data'
  | 'services'
  | 'workspace'
  | 'about'

export const CATEGORIES: { id: CategoryId; label: string; icon: React.ReactNode }[] = [
  { id: 'general', label: '通用', icon: <Settings2 aria-hidden className="size-4 shrink-0" /> },
  { id: 'appearance', label: '外观', icon: <Palette aria-hidden className="size-4 shrink-0" /> },
  { id: 'reading', label: '阅读', icon: <BookOpenText aria-hidden className="size-4 shrink-0" /> },
  { id: 'shortcuts', label: '快捷键', icon: <Keyboard aria-hidden className="size-4 shrink-0" /> },
  { id: 'translation', label: '翻译', icon: <Languages aria-hidden className="size-4 shrink-0" /> },
  { id: 'filters', label: '文章过滤', icon: <Filter aria-hidden className="size-4 shrink-0" /> },
  { id: 'rsshub', label: 'RSSHub', icon: <Satellite aria-hidden className="size-4 shrink-0" /> },
  { id: 'sources', label: '订阅与来源', icon: <Rss aria-hidden className="size-4 shrink-0" /> },
  { id: 'ai', label: 'AI', icon: <Bot aria-hidden className="size-4 shrink-0" /> },
  { id: 'data', label: '数据控制', icon: <Database aria-hidden className="size-4 shrink-0" /> },
  { id: 'services', label: '账户与服务', icon: <UserCog aria-hidden className="size-4 shrink-0" /> },
  { id: 'workspace', label: '工作区', icon: <LayoutGrid aria-hidden className="size-4 shrink-0" /> },
  { id: 'about', label: '关于', icon: <Info aria-hidden className="size-4 shrink-0" /> },
]

/** 旧分类 id → 新归属（设置分类是组件内 state，无 URL 深链；
 * 此映射供任何历史入口/书签式调用方安全降级到「数据控制」）。 */
export function normalizeCategoryId(id: string): CategoryId {
  return id === ('backup' as CategoryId) ? 'data' : (id as CategoryId)
}

/** 移动端设置首页的分组（Folo mobile SettingsList 分组模式，inspired）。 */
export const CATEGORY_GROUPS: { label: string; ids: CategoryId[] }[] = [
  { label: '主设置', ids: ['general', 'appearance', 'reading', 'shortcuts', 'translation', 'filters', 'rsshub'] },
  { label: '数据', ids: ['data'] },
  { label: '订阅与增强', ids: ['sources', 'ai', 'workspace'] },
  { label: '其他', ids: ['services', 'about'] },
]

export function categoryLabel(id: CategoryId): string {
  return CATEGORIES.find((c) => c.id === id)?.label ?? id
}

// ---- 分类页（声明式条目；外观/通用真实，其余占位或 planned） ----

export function useCategoryItems(id: CategoryId): SettingItemDef[] {
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)
  const reset = useAppSettings((s) => s.reset)
  const queryClient = useQueryClient()

  switch (id) {
    case 'appearance':
      return [
        { type: 'title', value: '应用' },
        {
          type: 'select',
          label: '主题模式',
          description: '浅色 / 深色 / 跟随系统。',
          value: settings.themeMode,
          options: [
            { value: 'system', label: '跟随系统' },
            { value: 'light', label: '浅色' },
            { value: 'dark', label: '深色' },
          ] satisfies { value: ThemeMode; label: string }[],
          onChange: (v) => update({ themeMode: v as ThemeMode }),
        },
        // 0010a F1（AC10）：accent 色板 + 自定义取色（全站生效）
        { type: 'custom', node: <AccentColorPicker /> },
        {
          // 0010a F1（AC11）：全局界面字号（root rem 缩放，Folo 同方案）
          type: 'select',
          label: '界面字号',
          description: '全局 UI 缩放（正文另有独立设置）。',
          value: settings.uiFontSize,
          options: [
            { value: 15, label: '小（15px）' },
            { value: 16, label: '标准（16px）' },
            { value: 18, label: '大（18px）' },
            { value: 20, label: '特大（20px）' },
          ] satisfies { value: UiFontSize; label: string }[],
          onChange: (v) => update({ uiFontSize: v as UiFontSize }),
        },
        {
          // 0010a F1（AC12）：UI 字体四档
          type: 'select',
          label: '界面字体',
          value: settings.uiFontStack,
          options: [
            { value: 'default', label: '默认（Lumi Mist）' },
            { value: 'sans', label: '无衬线' },
            { value: 'serif', label: '衬线' },
            { value: 'mono', label: '等宽' },
          ] satisfies { value: UiFontStack; label: string }[],
          onChange: (v) => update({ uiFontStack: v as UiFontStack }),
        },
        {
          // 0010a F1（AC13）：减少动效（与系统偏好取或）
          type: 'toggle',
          label: '减少动效',
          description: '禁用过渡动画（与系统「减少动态效果」偏好叠加生效）。',
          checked: settings.reduceMotion,
          onCheckedChange: (v) => update({ reduceMotion: v }),
        },
      ]
    case 'reading':
      // 0017：独立「阅读」分类——全部 Reader 设置收拢于此（AD-0017-5）。
      // 排版 Slider 与 Reader Aa 面板共用同一 settings store。
      return [
        { type: 'title', value: '排版' },
        { type: 'custom', node: <ReaderTypographyControls /> },
        {
          type: 'select',
          label: '正文字体',
          value: settings.readerFontFamily,
          options: [
            { value: 'system', label: '默认（跟随界面）' },
            { value: 'sans', label: '无衬线' },
            { value: 'serif', label: '衬线' },
            { value: 'mono', label: '等宽' },
          ] satisfies { value: ReaderFontFamily; label: string }[],
          onChange: (v) => update({ readerFontFamily: v as ReaderFontFamily }),
        },
        {
          // 0010a F6（AC18）：两端对齐（中文 inter-ideograph）
          type: 'toggle',
          label: '两端对齐',
          description: '正文左右对齐（中文标点悬挂优化）。',
          checked: settings.readerJustify,
          onCheckedChange: (v) => update({ readerJustify: v }),
        },
        {
          // 0010a F6（AC19）：图片三模式（Reeder 报纸模式 inspired）
          type: 'select',
          label: '图片显示',
          value: settings.readerImageMode,
          options: [
            { value: 'all', label: '显示全部' },
            { value: 'grayscale', label: '灰度' },
            { value: 'hidden', label: '隐藏' },
          ] satisfies { value: ReaderImageMode; label: string }[],
          onChange: (v) => update({ readerImageMode: v as ReaderImageMode }),
        },
        { type: 'title', value: '背景与字体' },
        // 0012 Gate 2/3：自定义字体（WOFF2 上传 + 字体 URL）
        { type: 'custom', node: <ReaderFontManager /> },
        // 0010a F7（AC20–AC22）：排版预设一键切换/派生/导入导出
        { type: 'custom', node: <ReaderPresetPicker /> },
        // 0010a F6（AC16/AC17）：阅读背景色板 + 自定义 hex + WCAG 自适应文字
        { type: 'custom', node: <ReaderBackgroundPicker /> },
        { type: 'title', value: '中文排版' },
        // 0012 Gate 4：中文深度排版（首行缩进/标点悬挂/简繁/阅读时间/词首强调）
        { type: 'custom', node: <ChineseTypographySettings /> },
        // 0012 Gate 8：代码高亮（Shiki lazy）
        { type: 'custom', node: <CodeHighlightSettings /> },
        { type: 'title', value: '阅读行为' },
        {
          // 0017：滚动标记已读正式化（默认关；保守条件 + 手动未读保护）
          type: 'toggle',
          label: '滚动时标记已读',
          description:
            '文章完全滚出列表上方后才自动标记为已读（离开后短暂停顿确认，手动设为未读的文章不会在同一轮滚动中被再次标记）。',
          checked: settings.scrollMarkUnread,
          onCheckedChange: (v) => update({ scrollMarkUnread: v }),
        },
        { type: 'title', value: '自定义' },
        // 0010a F7（AC14）：自定义 CSS（仅作用于正文，自动前缀）
        { type: 'custom', node: <CustomCssEditor /> },
        // 0012 Gate 6：.lumitheme 主题包导出/导入/预览
        { type: 'custom', node: <ReaderThemePackSettings /> },
      ]
    case 'general':
      return [
        { type: 'title', value: '应用程序' },
        {
          type: 'custom',
          node: (
            <div className="flex items-center justify-between gap-4 py-3">
              <div className="min-w-0">
                <label className="text-sm font-medium leading-none text-[var(--lumi-text-primary)]">
                  界面语言
                </label>
                <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
                  应用界面当前使用的语言。
                </p>
              </div>
              <span className="shrink-0 text-sm text-[var(--lumi-text-secondary)]">简体中文</span>
            </div>
          ),
        },
        { type: 'title', value: '时间线' },
        {
          type: 'toggle',
          label: '已读条目变暗',
          description: '已读条目整体降低不透明度（保留字重差异，不只靠颜色）。',
          checked: settings.dimRead,
          onCheckedChange: (v) => update({ dimRead: v }),
        },
        {
          type: 'toggle',
          label: '按日期分组',
          description: '在文章列表中插入日期小节标题（今天 / 昨天 / 更早）。',
          checked: settings.groupByDate,
          onCheckedChange: (v) => update({ groupByDate: v }),
        },
        {
          type: 'toggle',
          label: '启动时仅看未读',
          description: '打开应用时默认进入未读视图（不影响会话内手动切换）。',
          checked: settings.unreadOnly,
          onCheckedChange: (v) => update({ unreadOnly: v }),
        },
      ]
    case 'shortcuts':
      return [
        {
          type: 'custom',
          node: (
            <div className="py-2">
              <p className="mb-3 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
                列表上下文中的基础快捷键；输入框聚焦时不生效。
              </p>
              <dl className="divide-y divide-[var(--lumi-separator)]">
                {SHORTCUTS.map((s) => (
                  <div key={s.keys} className="flex items-center justify-between gap-4 py-2.5">
                    <dt className="text-sm text-[var(--lumi-text-primary)]">{s.action}</dt>
                    <dd>
                      <kbd className="rounded-[var(--lumi-radius-sm)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-0.5 font-mono text-xs text-[var(--lumi-text-secondary)]">
                        {s.keys}
                      </kbd>
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          ),
        },
      ]
    case 'translation':
      return [
        {
          type: 'custom',
          node: (
            <div className="py-3">
              <label className="text-sm font-medium leading-none text-[var(--lumi-text-primary)]">
                正文翻译
              </label>
              <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
                翻译由 AI Provider 驱动，在阅读页「原文/译文」切换使用；
                译文按文章缓存，不修改原始内容，也不在浏览器保存任何 API Key。
              </p>
              <p className="mt-2 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
                翻译使用的 AI 配置与目标语言在「AI」分类设置；未配置时翻译入口会如实提示并引导配置。
              </p>
            </div>
          ),
        },
      ]
    case 'filters':
      // 0010a F3（AC24）：OrigRead 过滤页复刻 + 显示层过滤
      return [{ type: 'custom', node: <FilterRulesSection /> }]
    case 'rsshub':
      // 唯一真实控制面：服务端 RSSHUB_BASE_URL + Control Center（配置 /
      // 密钥 / 应用引导）。浏览器侧「参考实例清单」假控制已退役。
      return [{ type: 'custom', node: <RssHubControlCenter /> }]
    case 'sources':
      return [
        { type: 'title', value: '订阅管理' },
        // OPML 导入/导出 + FreshRSS 状态/高级入口（真实可用）
        { type: 'custom', node: <SourcesSettingsSection /> },
      ]
    case 'ai':
      return [
        { type: 'title', value: 'AI 配置' },
        { type: 'custom', node: <AiSettingsSection /> },
      ]
    case 'data':
      // 数据控制 = 缓存 / 设置 / 配置迁移 / 完整备份 / 备份历史 / WebDAV / 恢复
      return [
        { type: 'title', value: '缓存' },
        {
          type: 'action',
          label: '清除本地缓存',
          description: '清空文章列表与详情的本地缓存，下次访问重新拉取（不影响阅读状态）。',
          buttonText: '清除',
          action: () => {
            queryClient.clear()
          },
        },
        { type: 'title', value: '设置' },
        {
          type: 'action',
          label: '恢复默认设置',
          description: '把外观、阅读等设置重置为默认值（portable 设置会同步重置到服务端，跨设备一致）。',
          buttonText: '重置',
          danger: true,
          action: () => reset(),
        },
        { type: 'title', value: '配置迁移与备份' },
        { type: 'custom', node: <DataBackupSection /> },
      ]
    case 'services':
      // 0018 Gate 9：账户与服务 —— 真实依赖状态（不再 plannedFor 0018）
      return [{ type: 'custom', node: <OperationsSettingsSection /> }]
    case 'workspace':
      return [
        {
          type: 'custom',
          node: (
            <div className="py-4">
              <div className="flex items-center gap-2">
                <Sparkles aria-hidden className="size-4 text-[var(--lumi-text-tertiary)]" />
                <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">
                  知识工作台
                </h3>
                <span className="ml-auto rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-2 py-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">
                  规划中
                </span>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
                网页剪藏、API 来源、邮件简报、Obsidian 库与 Agent
                工作台将按真实需求逐项设计。本页为占位，无可用功能。
              </p>
            </div>
          ),
        },
      ]
    case 'about':
      return [
        {
          type: 'custom',
          node: (
            <div className="py-4">
              <div className="flex items-center gap-2.5">
                <FileText aria-hidden className="size-5 text-[var(--lumi-text-tertiary)]" />
                <div>
                  <p className="text-sm font-semibold text-[var(--lumi-text-primary)]">LumiRSS</p>
                  <p className="text-xs text-[var(--lumi-text-secondary)]">流光阅源</p>
                </div>
              </div>
              <dl className="mt-4 divide-y divide-[var(--lumi-separator)] text-sm">
                <div className="flex items-center justify-between py-2.5">
                  <dt className="text-[var(--lumi-text-secondary)]">许可证</dt>
                  <dd className="text-[var(--lumi-text-primary)]">AGPL-3.0-only</dd>
                </div>
                <div className="flex items-center justify-between py-2.5">
                  <dt className="text-[var(--lumi-text-secondary)]">仓库</dt>
                  <dd>
                    <a
                      href="https://github.com/paidethon/LumiRSS"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-[var(--lumi-accent-text)] hover:underline"
                    >
                      paidethon/LumiRSS
                      <ExternalLink aria-hidden className="size-3" />
                    </a>
                  </dd>
                </div>
                <div className="flex items-center justify-between py-2.5">
                  <dt className="text-[var(--lumi-text-secondary)]">第三方声明</dt>
                  <dd>
                    <a
                      href="https://github.com/paidethon/LumiRSS/blob/main/THIRD_PARTY_NOTICES.md"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-[var(--lumi-accent-text)] hover:underline"
                    >
                      THIRD_PARTY_NOTICES
                      <ExternalLink aria-hidden className="size-3" />
                    </a>
                  </dd>
                </div>
              </dl>
              <AboutVersion />
              <p className="mt-4 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
                界面交互参考 Folo 与 OrigRead（inspired，独立实现）；来源映射见
                docs/reference/SOURCE_MAP.md。
              </p>
            </div>
          ),
        },
      ]
    default:
      return []
  }
}
