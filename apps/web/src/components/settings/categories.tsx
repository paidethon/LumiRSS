/** 设置分类共享模块 — 0010a Gate E。
 *
 * E1（AC5）：分类内容与分类定义从 SettingsModal 抽出，桌面 Modal 与
 * 移动 MobileSettingsScreen 共享同一组数据/组件（Folo 的共享方式：
 * 数据层与分类页共享，外壳各自实现）。
 *
 * E3（AC4）：分类 9 → 13——新增 翻译 / 文章过滤 / RSSHub / 备份与恢复
 * （本 Gate 为占位页，Gate F 填充完整功能）。
 *
 * planned 归属编号随路线修订顺延（当前归属见 docs/ROADMAP.md 变更记录）。 */

import { useQueryClient } from '@tanstack/react-query'
import {
  Bot,
  Database,
  DatabaseBackup,
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
  ReaderContentWidth,
  ReaderFontSize,
  ReaderFontFamily,
  ReaderImageMode,
  ReaderParagraphSpacing,
  ReaderLineHeight,
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
import { TranslationSettingsSection } from './TranslationSettingsPage'
import { FilterRulesSection } from './FilterRulesPage'
import { RssHubSettingsSection } from './RssHubSettingsPage'
import { BackupSettingsSection } from './BackupSettingsPage'

// ---- 分类定义（13 项；Folo 桌面 14 tab → Lumi 单用户裁剪） ----

export type CategoryId =
  | 'general'
  | 'appearance'
  | 'shortcuts'
  | 'sources'
  | 'ai'
  | 'translation'
  | 'filters'
  | 'rsshub'
  | 'data'
  | 'backup'
  | 'services'
  | 'workspace'
  | 'about'

export const CATEGORIES: { id: CategoryId; label: string; icon: React.ReactNode }[] = [
  { id: 'general', label: '通用', icon: <Settings2 aria-hidden className="size-4 shrink-0" /> },
  { id: 'appearance', label: '外观', icon: <Palette aria-hidden className="size-4 shrink-0" /> },
  { id: 'shortcuts', label: '快捷键', icon: <Keyboard aria-hidden className="size-4 shrink-0" /> },
  { id: 'translation', label: '翻译', icon: <Languages aria-hidden className="size-4 shrink-0" /> },
  { id: 'filters', label: '文章过滤', icon: <Filter aria-hidden className="size-4 shrink-0" /> },
  { id: 'rsshub', label: 'RSSHub', icon: <Satellite aria-hidden className="size-4 shrink-0" /> },
  { id: 'sources', label: '订阅与来源', icon: <Rss aria-hidden className="size-4 shrink-0" /> },
  { id: 'ai', label: 'AI', icon: <Bot aria-hidden className="size-4 shrink-0" /> },
  { id: 'data', label: '数据控制', icon: <Database aria-hidden className="size-4 shrink-0" /> },
  { id: 'backup', label: '备份与恢复', icon: <DatabaseBackup aria-hidden className="size-4 shrink-0" /> },
  { id: 'services', label: '账户与服务', icon: <UserCog aria-hidden className="size-4 shrink-0" /> },
  { id: 'workspace', label: '工作区', icon: <LayoutGrid aria-hidden className="size-4 shrink-0" /> },
  { id: 'about', label: '关于', icon: <Info aria-hidden className="size-4 shrink-0" /> },
]

/** 移动端设置首页的分组（Folo mobile SettingsList 分组模式，inspired）。 */
export const CATEGORY_GROUPS: { label: string; ids: CategoryId[] }[] = [
  { label: '主设置', ids: ['general', 'appearance', 'shortcuts', 'translation', 'filters', 'rsshub'] },
  { label: '数据', ids: ['data', 'backup'] },
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
        { type: 'title', value: '阅读' },
        // 0010a F7（AC20–AC22）：排版预设一键切换/派生/导入导出
        { type: 'custom', node: <ReaderPresetPicker /> },
        // 0010a F6（AC16/AC17）：阅读背景色板 + 自定义 hex + WCAG 自适应文字
        { type: 'custom', node: <ReaderBackgroundPicker /> },
        {
          // 0010a F6（AC15）：字体族四档
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
          type: 'select',
          label: '正文字号',
          value: settings.readerFontSize,
          options: [
            { value: 15, label: '小（15px）' },
            { value: 17, label: '标准（17px）' },
            { value: 19, label: '大（19px）' },
            { value: 21, label: '特大（21px）' },
          ] satisfies { value: ReaderFontSize; label: string }[],
          onChange: (v) => update({ readerFontSize: v as ReaderFontSize }),
        },
        {
          type: 'select',
          label: '正文行高',
          value: settings.readerLineHeight,
          options: [
            { value: 1.65, label: '紧凑（1.65）' },
            { value: 1.85, label: '标准（1.85）' },
            { value: 2.05, label: '宽松（2.05）' },
          ] satisfies { value: ReaderLineHeight; label: string }[],
          onChange: (v) => update({ readerLineHeight: v as ReaderLineHeight }),
        },
        {
          // 0010a F6（AC18）：段距三档
          type: 'select',
          label: '段落间距',
          value: settings.readerParagraphSpacing,
          options: [
            { value: 'compact', label: '紧凑' },
            { value: 'normal', label: '标准' },
            { value: 'loose', label: '宽松' },
          ] satisfies { value: ReaderParagraphSpacing; label: string }[],
          onChange: (v) => update({ readerParagraphSpacing: v as ReaderParagraphSpacing }),
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
        {
          type: 'select',
          label: '正文宽度',
          value: settings.readerContentWidth,
          options: [
            { value: 680, label: '窄（680px）' },
            { value: 760, label: '标准（760px）' },
            { value: 900, label: '宽（900px）' },
          ] satisfies { value: ReaderContentWidth; label: string }[],
          onChange: (v) => update({ readerContentWidth: v as ReaderContentWidth }),
        },
        { type: 'title', value: '自定义' },
        // 0010a F7（AC14）：自定义 CSS（仅作用于正文，自动前缀）
        { type: 'custom', node: <CustomCssEditor /> },
      ]
    case 'general':
      return [
        { type: 'title', value: '应用程序' },
        {
          type: 'select',
          label: '界面语言',
          value: settings.language,
          options: [
            { value: 'zh-CN', label: '简体中文' },
            { value: 'en', label: 'English' },
          ],
          onChange: () => {
            /* 仅 zh-CN 可选（en planned）；options 里 en 只是展示 */
          },
          planned: true,
          plannedFor: 'i18n',
          description: '当前仅支持简体中文；English 将随国际化工作提供。',
        },
        { type: 'title', value: '订阅' },
        {
          type: 'toggle',
          label: '侧栏隐藏已读',
          description:
            '隐藏没有未读条目的订阅（需要 feeds 接口提供未读数，0013 接线）。',
          checked: settings.sidebarHideRead,
          onCheckedChange: (v) => update({ sidebarHideRead: v }),
          planned: true,
          plannedFor: '0013',
        },
        { type: 'title', value: '时间线' },
        {
          type: 'toggle',
          label: '显示未读圆点',
          description: '在文章列表左侧显示未读标记圆点。',
          checked: settings.timelineUnreadDot,
          onCheckedChange: (v) => update({ timelineUnreadDot: v }),
        },
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
        {
          type: 'toggle',
          label: '滚动时标记已读',
          description:
            '文章完全滚出列表可视区后自动标记为已读（保守策略）。实验性：行为可能调整。',
          checked: settings.scrollMarkUnread,
          onCheckedChange: (v) => update({ scrollMarkUnread: v }),
          experimental: true,
          experimentalFor: '0017',
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
      // 0010a F2（AC23）：OrigRead 翻译页复刻
      return [{ type: 'custom', node: <TranslationSettingsSection /> }]
    case 'filters':
      // 0010a F3（AC24）：OrigRead 过滤页复刻 + 显示层过滤
      return [{ type: 'custom', node: <FilterRulesSection /> }]
    case 'rsshub':
      // 0010a F4（AC25）：OrigRead RSSHub 页复刻（16 内置实例）
      return [{ type: 'custom', node: <RssHubSettingsSection /> }]
    case 'backup':
      // 0010a F5（AC26/AC27）：配置备份导出/导入 + Web Crypto 加密
      return [{ type: 'custom', node: <BackupSettingsSection /> }]
    case 'sources':
      return [
        { type: 'title', value: '订阅管理' },
        {
          type: 'action',
          label: '添加订阅',
          description: '直接输入 RSS 地址或从发现页搜索（0013 Unified Subscription Center）。',
          buttonText: '添加',
          action: () => {},
          planned: true,
          plannedFor: '0013',
        },
        {
          type: 'action',
          label: '导入 / 导出 OPML',
          description: '迁移订阅列表（0013 经 FreshRSSControlAdapter）。',
          buttonText: '导入',
          action: () => {},
          planned: true,
          plannedFor: '0013',
        },
        {
          type: 'action',
          label: 'RSSHub 路由',
          description: '搜索与预览 RSSHub 路由（0014 Source Discovery）。',
          buttonText: '打开',
          action: () => {},
          planned: true,
          plannedFor: '0014',
        },
      ]
    case 'ai':
      return [
        { type: 'title', value: 'AI 增强' },
        {
          type: 'toggle',
          label: 'AI 总结',
          description: '阅读时生成单篇摘要（0015 AI Foundation & Summary）。',
          checked: false,
          onCheckedChange: () => {},
          planned: true,
          plannedFor: '0015',
        },
        {
          type: 'toggle',
          label: 'AI 翻译',
          description: '标题与正文翻译（0016）。',
          checked: false,
          onCheckedChange: () => {},
          planned: true,
          plannedFor: '0016',
        },
        {
          type: 'select',
          label: 'Provider',
          description: 'OpenAI-compatible API 配置（0015）。',
          value: 'openai' as const,
          options: [
            { value: 'openai', label: 'OpenAI compatible' },
          ],
          onChange: () => {},
          planned: true,
          plannedFor: '0015',
        },
      ]
    case 'data':
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
          description: '把外观、阅读等本地设置重置为默认值。',
          buttonText: '重置',
          danger: true,
          action: () => reset(),
        },
        { type: 'title', value: '备份' },
        {
          type: 'action',
          label: '数据备份 / 恢复',
          description: 'FreshRSS 数据与服务设置的备份演练（0018 Production）。',
          buttonText: '备份',
          action: () => {},
          planned: true,
          plannedFor: '0018',
        },
      ]
    case 'services':
      return [
        { type: 'title', value: '服务' },
        {
          type: 'action',
          label: 'FreshRSS 状态',
          description: '连接状态与健康检查（0013 接入控制平面后提供）。',
          buttonText: '查看',
          action: () => {},
          planned: true,
          plannedFor: '0013',
        },
        {
          type: 'action',
          label: 'RSSHub 状态',
          description: '实例健康与路由可用性（0014）。',
          buttonText: '查看',
          action: () => {},
          planned: true,
          plannedFor: '0014',
        },
      ]
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
                  Phase 2
                </span>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
                网页剪藏、API 来源、邮件简报、Obsidian 库与 Agent
                工作台将在 MVP（0019）之后按真实需求逐项设计（见 ROADMAP
                Phase 2）。本页为占位，无可用功能。
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
                  <dt className="text-[var(--lumi-text-secondary)]">版本</dt>
                  <dd className="font-mono text-xs text-[var(--lumi-text-primary)]">dev (0010)</dd>
                </div>
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
                      className="inline-flex items-center gap-1 text-[var(--lumi-accent)] hover:underline"
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
                      className="inline-flex items-center gap-1 text-[var(--lumi-accent)] hover:underline"
                    >
                      THIRD_PARTY_NOTICES
                      <ExternalLink aria-hidden className="size-3" />
                    </a>
                  </dd>
                </div>
              </dl>
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
