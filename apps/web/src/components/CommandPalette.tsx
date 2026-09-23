/** CommandPalette — F30 命令面板（Ctrl/⌘+K / 抽屉底部按钮唤起）。
 *
 * 命令来源：lib/command-registry.buildCommands —— 全部复用既有 action
 * （selectSection / selectView / settings.update / goBack），本组件不
 * 实现任何业务动作，只做：唤起、输入过滤（registry 的 casefold
 * includes）、上下键选择、Enter 执行、Escape 关闭。
 *
 * 打开通道：
 * - keyboard-shortcuts 全局 Ctrl/⌘+K 派发 COMMAND_PALETTE_TOGGLE_EVENT，
 *   本组件挂载后监听（挂载点：MobileNavigationDrawer，始终在树）；
 * - 抽屉底部「命令面板」按钮派发同一事件。
 *
 * 返回链：open 时 registerOverlay（浏览器后退只关这一层），关闭时
 * unregisterOverlay。浮层本体经 createPortal 挂到 body（挂载点在
 * lg:hidden 容器内，portal 使其桌面端同样可用）。
 *
 * a11y：role=dialog + aria-modal + listbox/option + aria-activedescendant；
 * 打开时输入框 autofocus；无结果空态「没有匹配的命令」。 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { CornerDownLeft, Search } from 'lucide-react'
import { useReaderUi } from '../store/reader-ui'
import { useAppSettings } from '../store/app-settings'
import { goBack, registerOverlay, unregisterOverlay } from '../lib/nav-history'
import { COMMAND_PALETTE_TOGGLE_EVENT, shouldIgnoreKeyEvent } from '../lib/keyboard-shortcuts'
import {
  buildCommands,
  buildContextCommands,
  filterCommandsFuzzy,
  type Command,
} from '../lib/command-registry'
import { useSubscriptions, useSavedSearchViews } from '../api/queries'
import { getEntry } from '../api/client'
import {
  buildMarkdownExport,
  downloadTextFile,
  sanitizeFileName,
} from '../lib/reader-export'
import {
  SPEECH_MAX_CHARS,
  speakText,
  speechSynthesisAvailable,
} from '../lib/reader-speech'
import { isPrivacyEnabled } from '../lib/privacy-mask'
import { cx } from './ui/cx'

const OVERLAY_ID = 'command-palette'

export default function CommandPalette() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  // F120：关闭回焦——打开时记住触发元素，关闭后把焦点还给它
  const returnFocusRef = useRef<HTMLElement | null>(null)

  const section = useReaderUi((s) => s.section)
  const view = useReaderUi((s) => s.view)
  const selectSection = useReaderUi((s) => s.selectSection)
  const selectView = useReaderUi((s) => s.selectView)
  const themeMode = useAppSettings((s) => s.settings.themeMode)
  const glassEffect = useAppSettings((s) => s.settings.glassEffect)
  const listDensity = useAppSettings((s) => s.settings.listDensity)
  const listTimeFormat = useAppSettings((s) => s.settings.listTimeFormat)
  const updateSettings = useAppSettings((s) => s.update)

  const close = useCallback(() => setOpen(false), [])
  const toggle = useCallback(() => setOpen((prev) => !prev), [])

  // 全局唤起：Ctrl/⌘+K（keyboard-shortcuts 派发）与抽屉按钮共用同一事件
  useEffect(() => {
    const onToggle = () => {
      // F120：打开瞬间记录回焦目标（autofocus 抢占 activeElement 之前）
      if (!open) {
        returnFocusRef.current =
          document.activeElement instanceof HTMLElement ? document.activeElement : null
      }
      toggle()
    }
    window.addEventListener(COMMAND_PALETTE_TOGGLE_EVENT, onToggle)
    return () => window.removeEventListener(COMMAND_PALETTE_TOGGLE_EVENT, onToggle)
  }, [toggle, open])

  // 返回链：打开登记浮层（后退只关这一层），关闭消耗自己的条目
  useEffect(() => {
    if (!open) return
    registerOverlay(OVERLAY_ID, close)
    return () => unregisterOverlay(OVERLAY_ID)
  }, [open, close])

  // 打开时重置查询与选中项；关闭时把焦点还给触发元素（F120 回焦）
  useEffect(() => {
    if (open) {
      setQuery('')
      setActiveIndex(0)
      return
    }
    const target = returnFocusRef.current
    returnFocusRef.current = null
    if (target !== null && typeof target.focus === 'function') target.focus()
  }, [open])

  // F120：数据源（订阅来源 / 保存的视图）与上下文动作所需的 reader 状态
  const selectedEntryRef = useReaderUi((s) => s.selectedEntryRef)
  const selectScope = useReaderUi((s) => s.selectScope)
  const subscriptions = useSubscriptions()
  const savedViews = useSavedSearchViews()

  const commands = useMemo(() => {
    const base = buildCommands(
      {
        section,
        view,
        themeMode,
        glassEffect,
        listDensity,
        listTimeFormat,
        capabilities: {
          privacyDemoOn: isPrivacyEnabled(),
          speechEnabled: speechSynthesisAvailable(),
        },
        // 防御：mock/降级上下文里缓存可能不是数组——形状不符按空处理，
        // 不让面板把异常抛到全局（缓存形状回归 A 同类教训）。
        subscriptions: (Array.isArray(subscriptions.data) ? subscriptions.data : []).map((sub) => ({
          id: sub.subscriptionRef,
          title: sub.title,
          open: () => {
            selectScope({ kind: 'rss-feed', feedUrl: sub.feedUrl })
            selectSection('home')
          },
        })),
        savedViews: (savedViews.data?.items ?? []).map((saved) => ({
          id: saved.id,
          title: saved.name,
          open: () => {
            selectSection('search')
            window.dispatchEvent(
              new CustomEvent('lumirss-open-saved-view', {
                detail: {
                  query: saved.query,
                  view: saved.view,
                  categoryKey: saved.categoryKey,
                },
              }),
            )
          },
        })),
      },
      {
        selectSection,
        selectView,
        updateSettings,
        goBack: () => {
          goBack()
        },
      },
    )
    // F120：section 上下文动作（导出/朗读当前文章；无选中文章/privacy
    // 开启/语音不可用时不装配）
    const context = buildContextCommands(
      {
        section,
        view,
        themeMode,
        glassEffect,
        listDensity,
        listTimeFormat,
        capabilities: {
          privacyDemoOn: isPrivacyEnabled(),
          speechEnabled: speechSynthesisAvailable(),
        },
      },
      {
        exportReader:
          selectedEntryRef !== null
            ? () => {
                void getEntry(selectedEntryRef).then((detail) => {
                  downloadTextFile(
                    `${sanitizeFileName(detail.title) || 'article'}.md`,
                    buildMarkdownExport({
                      title: detail.title,
                      source: detail.feedTitle,
                      date: (detail.publishedAt ?? '').slice(0, 10),
                      url: detail.url ?? null,
                      text: detail.contentText,
                      html: detail.contentHtml ?? null,
                    }),
                    'text/markdown',
                  )
                })
              }
            : undefined,
        speakReader:
          selectedEntryRef !== null && speechSynthesisAvailable()
            ? () => {
                void getEntry(selectedEntryRef).then((detail) => {
                  speakText(detail.contentText.slice(0, SPEECH_MAX_CHARS), { rate: 1 })
                })
              }
            : undefined,
      },
    )
    return [...base, ...context]
  }, [
    section,
    view,
    themeMode,
    glassEffect,
    listDensity,
    listTimeFormat,
    selectSection,
    selectView,
    selectScope,
    updateSettings,
    selectedEntryRef,
    subscriptions.data,
    savedViews.data,
  ])
  // F120：子序列模糊打分（连续命中 > 分隔命中），同分保持原顺序
  const filtered = useMemo(() => filterCommandsFuzzy(commands, query), [commands, query])

  // 过滤结果变化时把选中项拉回界内
  useEffect(() => {
    setActiveIndex((index) => Math.min(index, Math.max(0, filtered.length - 1)))
  }, [filtered.length])

  const runCommand = useCallback(
    (command: Command) => {
      // 先关面板（消耗浮层历史条目）再执行命令
      close()
      command.run()
    },
    [close],
  )

  const onInputKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    // P13：IME 组合中的按键不驱动面板（Enter 上屏 / Esc 取消组合交还原生行为）
    if (shouldIgnoreKeyEvent(event.nativeEvent)) return
    if (event.key === 'Escape') {
      event.preventDefault()
      close()
      return
    }
    // 面板自身输入框聚焦时 Ctrl/⌘+K 关闭（全局快捷键对输入框不劫持）
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault()
      close()
      return
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      if (filtered.length > 0) setActiveIndex((index) => (index + 1) % filtered.length)
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      if (filtered.length > 0) setActiveIndex((index) => (index - 1 + filtered.length) % filtered.length)
      return
    }
    if (event.key === 'Enter') {
      event.preventDefault()
      const command = filtered[activeIndex]
      if (command !== undefined) runCommand(command)
    }
  }

  if (!open) return null

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="命令面板"
      data-testid="command-palette"
      className="fixed inset-0 z-[calc(var(--lumi-z-dialog)_+_1)] flex items-start justify-center px-4 pt-[10vh]"
    >
      {/* 遮罩（点击关闭） */}
      <button
        type="button"
        aria-label="关闭命令面板"
        onClick={close}
        className="absolute inset-0 size-full cursor-default bg-[var(--lumi-text-primary)]/30"
      />
      <div className="relative flex w-[min(92vw,32rem)] flex-col overflow-hidden rounded-[var(--lumi-radius-xl)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] shadow-[var(--lumi-shadow-dialog)]">
        {/* 搜索输入：过滤 + 键盘导航 */}
        <div className="flex shrink-0 items-center gap-2 border-b border-[var(--lumi-separator)] px-3.5 py-2">
          <Search aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />
          <input
            ref={inputRef}
            autoFocus
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setActiveIndex(0)
            }}
            onKeyDown={onInputKeyDown}
            placeholder="搜索命令…"
            aria-label="搜索命令"
            role="combobox"
            aria-expanded="true"
            aria-controls="command-palette-listbox"
            aria-activedescendant={
              filtered.length > 0 ? `command-option-${activeIndex}` : undefined
            }
            className="min-h-11 w-full bg-transparent text-sm text-[var(--lumi-text-primary)] outline-none placeholder:text-[var(--lumi-text-tertiary)]"
          />
        </div>
        {/* 命令列表（title/keywords 过滤；上下键 + Enter；空态诚实） */}
        <ul
          id="command-palette-listbox"
          role="listbox"
          aria-label="命令列表"
          className="max-h-[50dvh] min-h-0 flex-1 overflow-y-auto p-1.5"
        >
          {filtered.length === 0 ? (
            <li
              role="status"
              className="px-3 py-8 text-center text-sm text-[var(--lumi-text-tertiary)]"
            >
              没有匹配的命令
            </li>
          ) : (
            filtered.map((command, index) => (
              <li
                key={command.id}
                id={`command-option-${index}`}
                role="option"
                aria-selected={index === activeIndex}
              >
                <button
                  type="button"
                  data-command-id={command.id}
                  onClick={() => runCommand(command)}
                  onMouseEnter={() => setActiveIndex(index)}
                  className={cx(
                    'flex min-h-11 w-full items-center gap-2 rounded-[var(--lumi-radius-md)] px-2.5 py-1.5 text-left text-sm transition-colors duration-[var(--lumi-motion-fast)]',
                    index === activeIndex
                      ? 'bg-[var(--lumi-accent-soft)] font-medium text-[var(--lumi-accent-text)]'
                      : 'text-[var(--lumi-text-primary)] hover:bg-[var(--lumi-surface-hover)]',
                  )}
                >
                  <span className="min-w-0 flex-1 truncate">{command.title}</span>
                  <span className="shrink-0 text-xs text-[var(--lumi-text-tertiary)]">
                    {command.section}
                  </span>
                  {index === activeIndex && (
                    <CornerDownLeft aria-hidden className="size-3.5 shrink-0" />
                  )}
                </button>
              </li>
            ))
          )}
        </ul>
      </div>
    </div>,
    document.body,
  )
}
