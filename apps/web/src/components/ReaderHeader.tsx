import { Fragment, lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  BookMarked,
  Camera, Check, Clock, ExternalLink, FileCode, FileText, Languages,
  Link2, Loader2, MessageSquare, MoreHorizontal, Pause, Play, Printer, Quote,
  Search, Settings2, Share2, Square, Star, Volume2, X,
} from 'lucide-react'
import type { EntryDetail } from '../api/types'
import { useAiSettings, useCreateSnapshotMutation, useEntryStateMutation } from '../api/queries'
import { getEntry } from '../api/client'
import { useQueryClient } from '@tanstack/react-query'
import { useToggleReadLater } from '../lib/read-later'
import { safeExternalHttpUrl } from '../lib/safe-external-http-url'
import { formatReadingTime, textFromHtml } from '../lib/reading-time'
import { dateTimeFormatter as dateFormatter } from '../lib/date-format'
import { localTranslatorAvailable } from '../lib/local-translator'
import { SourceGlyph, SourceLabel } from '../lib/source-meta'
import { useIsMobile } from '../lib/use-is-mobile'
import { useAppSettings } from '../store/app-settings'
import { useUndo } from '../store/undo'
import {
  buildQuoteMarkdownText,
  buildQuotePlainText,
  fallbackShareUrl,
  QUOTE_MAX_CHARS,
  type AutoScrollState,
} from '../lib/reader-tools'
// P16 导出到 Obsidian：懒加载入口（bundle guard 懒加载契约——阅读页
// 首屏不携带对话框实现，仅在打开时拉取 chunk）。
const ObsidianExportDialog = lazy(() => import('./ObsidianExportDialog'))
import {
  ReaderSpeechEngine,
  SPEECH_BILINGUAL_GAPS,
  SPEECH_LEXICON_CAP,
  SPEECH_RATES,
  SPEECH_SLEEP_TIMER_MINUTES,
  bilingualGapMs,
  buildSpeechQueue,
  listVoices,
  markSpeechBlockElement,
  speechSynthesisAvailable,
  type SpeechBlockInfo,
  type SpeechBilingualGap,
  type SpeechCollection,
  type SpeechRate,
} from '../lib/reader-speech'
import {
  getSpeechBookmark,
  saveSpeechBookmark,
  type SpeechBookmark,
} from '../lib/speech-bookmarks'
import SpeechSelectionLayer from './SpeechSelectionLayer'
import { Switch } from './ui/Switch'
import type { AppSettings } from '../store/app-settings'
import {
  exportEntryAsHtml,
  exportEntryAsMarkdown,
  type ExportInput,
} from '../lib/reader-export'
import {
  readerToolbarAction,
  resolveReaderToolbarVisible,
  type ReaderToolbarActionId,
} from '../lib/reader-toolbar'
import ReaderToolbarCustomizeDialog from './ReaderToolbarCustomizeDialog'
import ReaderAaPanel from './ReaderAaPanel'
import type { ReaderViewMode } from '../lib/translation-blocks'
import { Button } from './ui/Button'
import { IconButton } from './ui/IconButton'
import { Menu, type MenuItemDef } from './ui/Menu'
import { Popover } from './ui/Popover'
import { Select } from './ui/Select'
import { Tooltip } from './ui/Tooltip'
import { cx } from './ui/cx'

function formatPublishedAt(value: string | null | undefined): string {
  if (value == null) {
    return ''
  }
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : dateFormatter.format(date)
}

/** phase2 Gate 3：保存快照（monolith 离线快照；仅绝对 http/https 原文
 * 可保存——由父级以 safeExternalHttpUrl 过滤后条件渲染）。
 * 成功短暂显示「快照已保存」；失败原样透出 BFF message
 *（monolith_unavailable / 配额超限等，诚实语义）。
 * O127：状态 hoist 到 ReaderHeader（useSnapshotAction），桌面工具栏按钮
 * 与移动端「更多操作」菜单项共享同一 mutation / 反馈。 */
function useSnapshotAction(url: string | null) {
  const [savedRecently, setSavedRecently] = useState(false)
  const createSnapshot = useCreateSnapshotMutation()

  const failure =
    createSnapshot.isError && createSnapshot.error instanceof Error
      ? createSnapshot.error.message
      : createSnapshot.isError
        ? '快照保存失败，请稍后重试。'
        : null
  const tooltip = failure ?? (savedRecently ? '快照已保存' : '保存快照')

  const save = () => {
    if (url === null) return
    createSnapshot.mutate(url, {
      onSuccess: () => {
        setSavedRecently(true)
        window.setTimeout(() => setSavedRecently(false), 3000)
      },
    })
  }

  return { pending: createSnapshot.isPending, savedRecently, tooltip, save }
}

/** SaveSnapshotButton — 桌面工具栏快照入口（移动端在「更多操作」菜单）。
 * O127：mutation/反馈已 hoist 到 useSnapshotAction（ReaderHeader 持有，
 * url 由其闭包捕获），按钮只消费状态。 */
function SaveSnapshotButton({
  snapshot,
}: {
  snapshot: ReturnType<typeof useSnapshotAction>
}) {

  return (
    <Tooltip content={snapshot.tooltip}>
      <IconButton
        icon={
          snapshot.pending ? (
            <Loader2 aria-hidden className="animate-spin" />
          ) : (
            <Camera
              aria-hidden
              className={cx(
                snapshot.savedRecently && 'text-[var(--lumi-accent-text)]',
              )}
            />
          )
        }
        label="保存快照"
        touch
        disabled={snapshot.pending}
        onClick={snapshot.save}
      />
    </Tooltip>
  )
}

/** P18 朗读控制状态（O127 hoist）：桌面工具栏按钮与移动端「更多操作」
 * 菜单项共享同一状态机。底层为逐块引擎（ReaderSpeechEngine）：每段一条
 * utterance，onBlockChange 驱动当前段高亮（data-speech-active）与面板
 * 进度；睡眠定时在块边界检查。点击循环 空闲→朗读→暂停→继续；「停止
 * 朗读」cancel 并复位。collectBlocks 由 Reader 提供（取视口顶部最近段
 * 落往后的全部块文本 + 起点索引）；hook 在 ReaderHeader（key=entryRef）
 * 内 —— 卸载即 stop，切文章自动停止朗读。
 *
 * NF1：启动路径统一为 startSpeaking（收集 → 配置 → buildSpeechQueue →
 * 引擎 speakQueue）——交替听读（N097）、排除/词典后的块 id 对齐
 * （N094/N095）都经此单点；speakFromBlock（N091 选区起点 / N092 书签
 * 续听）复用同一路径，引擎 cancel-first，既有播放自动停止。块 id
 * （selectorIndex）与队列位置解耦：预览表按块 id 取原文文本，与高亮
 * 一致。 */
function useSpeechControl(
  collectBlocks: (() => SpeechCollection | null) | undefined,
) {
  const [state, setState] = useState<'idle' | 'speaking' | 'paused'>('idle')
  const [error, setError] = useState<string | null>(null)
  /** 睡眠定时到点后的诚实提示（面板内展示；新会话/手动停止即清除）。 */
  const [sleepStopped, setSleepStopped] = useState(false)
  const [block, setBlock] = useState<(SpeechBlockInfo & { preview: string }) | null>(
    null,
  )
  const speechRate = useAppSettings((s) => s.settings.speechRate)
  const speechVoiceURI = useAppSettings((s) => s.settings.speechVoiceURI)
  const speechSleepMinutes = useAppSettings((s) => s.settings.speechSleepTimerMinutes)
  const updateSettings = useAppSettings((s) => s.update)
  const engineRef = useRef<ReaderSpeechEngine | null>(null)
  /** 当前会话的块 id → 出声文本（面板预览用；译文条目与原块共享 id，
   * 预览显示块原文，与高亮一致）。 */
  const blockTextsRef = useRef<Map<number, string>>(new Map())
  const stateRef = useRef(state)
  stateRef.current = state
  const available = speechSynthesisAvailable()

  // P18 段落跟踪：当前块 DOM 标记（正文左侧 accent 细条）；停止/卸载
  // 即清除。标记走 lib/reader-speech 的纯 DOM helper（文章不在文档时
  // 为无操作）。
  useEffect(() => {
    markSpeechBlockElement(state === 'idle' ? null : (block?.index ?? null))
  }, [state, block])
  // 切文章（key 重挂载）/卸载：stop 朗读（cancel + 清队列），绝不跨文章延续。
  useEffect(() => {
    return () => {
      markSpeechBlockElement(null)
      engineRef.current?.stop()
    }
  }, [])

  const getEngine = () => {
    if (engineRef.current === null) {
      engineRef.current = new ReaderSpeechEngine(
        {
          rate: speechRate,
          voiceURI: speechVoiceURI === '' ? null : speechVoiceURI,
          langPrefix: 'zh',
          interPairGapMs: bilingualGapMs(
            useAppSettings.getState().settings.speechBilingualGap,
          ),
        },
        {
          onBlockChange: (info) => {
            const preview = (blockTextsRef.current.get(info.index) ?? '')
              .trim()
              .slice(0, 40)
            setBlock({ ...info, preview })
          },
          onEnd: () => {
            setState('idle')
            setBlock(null)
          },
          onError: (message) => {
            setError(message)
            setState('idle')
            setBlock(null)
          },
          onSleepTimer: () => {
            setSleepStopped(true)
            setState('idle')
            setBlock(null)
          },
        },
      )
    }
    return engineRef.current
  }

  /** 统一启动：收集 → 读设置快照 → 建队列 → 从起点块入队。overrideStart
   * 为 null 时用收集结果的视口起点。 */
  const startSpeaking = (overrideStart: number | null) => {
    if (collectBlocks === undefined) return
    setError(null)
    setSleepStopped(false)
    const collection = collectBlocks()
    if (collection === null) {
      setError('没有可朗读的正文。')
      return
    }
    const s = useAppSettings.getState().settings
    const engine = getEngine()
    // cancel-first：若已有会话，先整体停机（cancel + 作废在途回调）——
    // 随后的 setConfig 只落配置，不再触发「重读旧队列当前段」的语义。
    if (engine.speaking) engine.stop()
    // 配置/定时以 settings store 当前值为准（不依赖渲染闭包）。
    engine.setConfig({
      rate: s.speechRate,
      voiceURI: s.speechVoiceURI === '' ? null : s.speechVoiceURI,
      interPairGapMs: bilingualGapMs(s.speechBilingualGap),
    })
    engine.armSleepTimer(s.speechSleepTimerMinutes > 0 ? s.speechSleepTimerMinutes : null)
    const items = buildSpeechQueue(collection, {
      bilingual: s.speechBilingualAlternate,
    })
    const blockTexts = new Map<number, string>()
    for (const item of items) {
      if (!blockTexts.has(item.blockIndex)) blockTexts.set(item.blockIndex, item.text)
    }
    blockTextsRef.current = blockTexts
    engine.speakQueue(items, overrideStart ?? collection.startIndex)
    if (!engine.speaking) {
      // 收集结果全为空块 → 引擎未出声，诚实报错（不假装在读）。
      setError('没有可朗读的正文。')
      setBlock(null)
      return
    }
    setState('speaking')
  }

  const toggle = () => {
    if (collectBlocks === undefined) return
    setError(null)
    setSleepStopped(false)
    if (state === 'idle') {
      startSpeaking(null)
      return
    }
    if (state === 'speaking') {
      engineRef.current?.pause()
      setState('paused')
      return
    }
    engineRef.current?.resume()
    setState('speaking')
  }

  /** NF1 N091/N092：从指定块开始朗读（选区「从此处朗读」/ 书签续听）。
   * 引擎 cancel-first——进行中的播放被替换为新会话。 */
  const speakFromBlock = (startBlockIndex: number) => {
    startSpeaking(startBlockIndex)
  }

  const stop = () => {
    engineRef.current?.stop()
    setState('idle')
    setBlock(null)
    setError(null)
    setSleepStopped(false)
  }

  const changeRate = (next: SpeechRate) => {
    updateSettings({ speechRate: next })
    // 朗读中调速：取消当前块并按新语速重读当前段（P18 段落跟踪，不再
    // 整篇从头）；暂停中只落配置，恢复后的块按新语速出声。
    if (engineRef.current !== null && stateRef.current === 'speaking') {
      engineRef.current.setConfig({ rate: next })
    }
  }

  const changeVoice = (uri: string) => {
    updateSettings({ speechVoiceURI: uri })
    if (engineRef.current !== null && stateRef.current === 'speaking') {
      engineRef.current.setConfig({ voiceURI: uri === '' ? null : uri })
    }
  }

  const changeSleepMinutes = (minutes: number) => {
    updateSettings({ speechSleepTimerMinutes: minutes })
    // 会话中改设定：deadline 即刻按新档位重新锚定（关 = 解除）。
    if (engineRef.current !== null && stateRef.current !== 'idle') {
      engineRef.current.armSleepTimer(minutes > 0 ? minutes : null)
    }
  }

  return {
    available,
    state,
    error,
    sleepStopped,
    block,
    rate: speechRate,
    voiceURI: speechVoiceURI,
    sleepMinutes: speechSleepMinutes,
    toggle,
    stop,
    changeRate,
    changeVoice,
    changeSleepMinutes,
    speakFromBlock,
  }
}

/** P18 朗读面板（Popover 内容）：当前段进度 + 预览、声音挑选、语速、
 * 睡眠定时。偏好全部落 settings store（设备本地）。声音清单来自
 * listVoices()（zh 组排最前——默认朗读语言；文章级语言元数据暂不可得，
 * 这是诚实的近似：全量声音仍可选）。系统声音清单为空（尚未加载/无
 * 声音）时只剩「自动」，不假装有候选项。
 *
 * NF1 扩展（均设备本地，段落级语义诚实标注）：
 * - N092 听读书签：保存当前朗读段；恢复走正文里的续听 chip（浏览器
 *   语音无法在句中定位，恢复按段开头，不做假装精确的进度）；
 * - N094 听读内容排除：五类块开关，只影响朗读收集（文章展示不动）；
 * - N095 发音词典：子串替换（大小写不敏感），只作用于出声/试听文本；
 * - N097 交替听读：原文 → 译文逐段交替（译文来自已有 overlay，缺译文
 *   只读原文，绝不发起翻译）+ 原文/译文间隔档位；
 * - 试听文本：按当前收集 + 交替设置给出真实将读内容的预览（首 300 字）。 */
const PANEL_ROW = 'flex min-h-9 items-center justify-between gap-3'

/** 面板分组（分隔线 + 弱化小标题 + 可选诚实说明）。 */
function PanelSection({
  title,
  note,
  children,
}: {
  title: string
  note?: string
  children: ReactNode
}) {
  return (
    <section className="flex flex-col gap-1.5 border-t border-[var(--lumi-separator)] pt-2.5">
      <h4 className="text-xs font-medium text-[var(--lumi-text-tertiary)]">{title}</h4>
      {children}
      {note !== undefined && (
        <p className="text-xs leading-5 text-[var(--lumi-text-tertiary)]">{note}</p>
      )}
    </section>
  )
}

/** N094 排除开关行定义（键与 settings store 对应；值由面板订阅注入）。 */
const SPEECH_EXCLUSION_ROWS = [
  { key: 'speechSkipCode', label: '跳过代码块' },
  { key: 'speechSkipTables', label: '跳过表格' },
  { key: 'speechSkipFootnotes', label: '跳过脚注' },
  { key: 'speechSkipCaptions', label: '跳过图片说明' },
  { key: 'speechSkipLinkOnly', label: '跳过纯链接段落' },
] as const

function SpeechPanelControls({
  speech,
  bookmark,
  onSaveBookmark,
  collectBlocks,
}: {
  speech: ReturnType<typeof useSpeechControl>
  bookmark: SpeechBookmark | null
  onSaveBookmark: (blockIndex: number) => void
  /** 试听文本与朗读同源的收集入口（排除/词典已在收集时生效）。 */
  collectBlocks?: () => SpeechCollection | null
}) {
  const voiceOptions = useMemo(() => {
    const groups = [...listVoices()].sort((a, b) => {
      const aZh = a.lang.startsWith('zh') ? 0 : 1
      const bZh = b.lang.startsWith('zh') ? 0 : 1
      return aZh - bZh || a.lang.localeCompare(b.lang)
    })
    return [
      { value: '', label: '自动（中文优先）' },
      ...groups.flatMap((group) =>
        group.voices.map((voice) => ({
          value: voice.voiceURI,
          label: `${voice.name}（${group.lang}）`,
        })),
      ),
    ]
  }, [])
  // 订阅听读偏好：试听文本随开关/词典/交替设置即时重算（收集回调在
  // 调用时刻读 store 快照——这里订阅保证重渲染时机）。
  const skipCode = useAppSettings((s) => s.settings.speechSkipCode)
  const skipTables = useAppSettings((s) => s.settings.speechSkipTables)
  const skipFootnotes = useAppSettings((s) => s.settings.speechSkipFootnotes)
  const skipCaptions = useAppSettings((s) => s.settings.speechSkipCaptions)
  const skipLinkOnly = useAppSettings((s) => s.settings.speechSkipLinkOnly)
  const lexicon = useAppSettings((s) => s.settings.speechLexicon)
  const bilingual = useAppSettings((s) => s.settings.speechBilingualAlternate)
  const bilingualGap = useAppSettings((s) => s.settings.speechBilingualGap)
  const updateSettings = useAppSettings((s) => s.update)
  const exclusionValues: Record<(typeof SPEECH_EXCLUSION_ROWS)[number]['key'], boolean> = {
    speechSkipCode: skipCode,
    speechSkipTables: skipTables,
    speechSkipFootnotes: skipFootnotes,
    speechSkipCaptions: skipCaptions,
    speechSkipLinkOnly: skipLinkOnly,
  }

  // ---- N095 发音词典（cap 50；空匹配拒绝） ----
  const [matchInput, setMatchInput] = useState('')
  const [replaceInput, setReplaceInput] = useState('')
  const [lexiconError, setLexiconError] = useState<string | null>(null)
  const addLexiconEntry = () => {
    const match = matchInput.trim()
    if (match === '') {
      setLexiconError('匹配词不能为空。')
      return
    }
    if (lexicon.length >= SPEECH_LEXICON_CAP) {
      setLexiconError(`最多 ${SPEECH_LEXICON_CAP} 条，请先删除旧条目。`)
      return
    }
    if (lexicon.some((e) => e.match.toLowerCase() === match.toLowerCase())) {
      setLexiconError('该匹配词已存在。')
      return
    }
    updateSettings({ speechLexicon: [...lexicon, { match, replace: replaceInput }] })
    setMatchInput('')
    setReplaceInput('')
    setLexiconError(null)
  }
  const removeLexiconEntry = (index: number) => {
    updateSettings({
      speechLexicon: lexicon.filter((_, i) => i !== index),
    })
  }

  // ---- N092 书签保存反馈 ----
  const [bookmarkNote, setBookmarkNote] = useState<string | null>(null)

  // ---- 试听文本（真实将读内容预览；交替听读含译文条目） ----
  const preview = useMemo(() => {
    if (collectBlocks === undefined) return null
    const collection = collectBlocks()
    if (collection === null) return null
    const items = buildSpeechQueue(collection, { bilingual })
    const joined = items
      .map((item) => item.text.trim())
      .filter((text) => text !== '')
      .join('\n\n')
    return { text: joined.slice(0, 300), truncated: joined.length > 300 }
    // skip*/lexicon 参与 Reader 收集（调用时刻读取），一并作为重算信号。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collectBlocks, bilingual, skipCode, skipTables, skipFootnotes, skipCaptions, skipLinkOnly, lexicon])

  return (
    <div
      className="flex max-h-[min(34rem,75vh)] w-full flex-col gap-2.5 overflow-y-auto"
      role="group"
      aria-label="朗读设置"
    >
      {/* 状态行：当前段落进度 + 首行预览；睡眠定时停止 = 诚实提示 */}
      {speech.sleepStopped ? (
        <p aria-live="polite" className="text-sm text-[var(--lumi-text-secondary)]">
          已停止（睡眠定时）
        </p>
      ) : speech.block !== null ? (
        <div aria-live="polite" className="min-w-0">
          <p className="text-xs text-[var(--lumi-text-tertiary)]">
            正在朗读 第 {speech.block.position} / {speech.block.total} 段
            {speech.state === 'paused' ? '（已暂停）' : ''}
          </p>
          <p className="mt-0.5 truncate text-sm text-[var(--lumi-text-primary)]">
            {speech.block.preview}
          </p>
        </div>
      ) : (
        <p className="text-sm text-[var(--lumi-text-secondary)]">未在朗读</p>
      )}

      {/* N092 听读书签：保存当前朗读段（未朗读时诚实禁用） */}
      <div className={PANEL_ROW}>
        <span className="text-sm text-[var(--lumi-text-primary)]">听读书签</span>
        <Button
          size="sm"
          variant="secondary"
          className="min-h-11"
          disabled={speech.block === null}
          title={
            speech.block === null
              ? '正在朗读时才可保存书签'
              : '保存当前段；恢复时从该段开头朗读（浏览器语音无法在句中定位）'
          }
          onClick={() => {
            const current = speech.block
            if (current === null) return
            onSaveBookmark(current.index)
            setBookmarkNote(`已保存书签（第 ${current.index + 1} 段）`)
            window.setTimeout(() => setBookmarkNote(null), 2000)
          }}
        >
          书签
        </Button>
      </div>
      {bookmark !== null && (
        <p className="text-xs leading-5 text-[var(--lumi-text-tertiary)]">
          已存书签：第 {bookmark.blockIndex + 1} 段
          {bookmarkNote !== null ? ` · ${bookmarkNote}` : ''}
        </p>
      )}
      {bookmark === null && bookmarkNote !== null && (
        <p aria-live="polite" className="text-xs text-[var(--lumi-accent-text)]">
          {bookmarkNote}
        </p>
      )}

      <PanelSection title="声音与节奏">
        <div className={PANEL_ROW}>
          <span className="text-sm text-[var(--lumi-text-primary)]">声音</span>
          <Select
            aria-label="朗读声音"
            value={speech.voiceURI}
            onChange={(e) => speech.changeVoice(e.target.value)}
            options={voiceOptions}
            className="max-w-[11.5rem]"
          />
        </div>

        <div className={PANEL_ROW}>
          <span className="text-sm text-[var(--lumi-text-primary)]">语速</span>
          <div role="group" aria-label="朗读语速" className="inline-flex gap-0.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-0.5">
            {SPEECH_RATES.map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={speech.rate === value}
                onClick={() => speech.changeRate(value)}
                className={cx(
                  'min-h-7 min-w-9 rounded-[var(--lumi-radius-sm)] px-1 text-xs tabular-nums transition-colors duration-[var(--lumi-motion-fast)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                  speech.rate === value
                    ? 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-primary)]'
                    : 'text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)]',
                )}
              >
                {value}x
              </button>
            ))}
          </div>
        </div>

        <div className={PANEL_ROW}>
          <span className="text-sm text-[var(--lumi-text-primary)]">睡眠定时</span>
          <div
            role="group"
            aria-label="朗读睡眠定时"
            className="flex flex-wrap justify-end gap-0.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-0.5"
          >
            {SPEECH_SLEEP_TIMER_MINUTES.map((minutes) => (
              <button
                key={minutes}
                type="button"
                aria-pressed={speech.sleepMinutes === minutes}
                onClick={() => speech.changeSleepMinutes(minutes)}
                className={cx(
                  'min-h-7 rounded-[var(--lumi-radius-sm)] px-1.5 text-xs transition-colors duration-[var(--lumi-motion-fast)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                  speech.sleepMinutes === minutes
                    ? 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-primary)]'
                    : 'text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)]',
                )}
              >
                {minutes === 0 ? '关' : `${minutes} 分`}
              </button>
            ))}
          </div>
        </div>

        {/* 睡眠定时语义的诚实说明：块边界检查 + 暂停可能推迟实际停止 */}
        <p className="text-xs leading-5 text-[var(--lumi-text-tertiary)]">
          定时在段落边界检查；暂停期间不推进段落，实际停止可能晚于设定。
        </p>
      </PanelSection>

      {/* N094 听读内容排除：只影响朗读范围，文章内容原样保留 */}
      <PanelSection title="听读内容排除" note="仅影响朗读范围；文章内容保持原样。">
        {SPEECH_EXCLUSION_ROWS.map((row) => (
          <div key={row.key} className={PANEL_ROW}>
            <span className="text-sm text-[var(--lumi-text-primary)]">{row.label}</span>
            <Switch
              checked={exclusionValues[row.key]}
              label={`朗读${row.label}`}
              onCheckedChange={(checked) =>
                updateSettings({ [row.key]: checked } as Partial<AppSettings>)
              }
            />
          </div>
        ))}
      </PanelSection>

      {/* N097 原文译文交替听读（需要已有译文；缺译文段诚实跳过） */}
      <PanelSection
        title="交替听读"
        note="每段先读原文再读已有译文；缺译文的段只读原文。改动在下一次朗读生效。"
      >
        <div className={PANEL_ROW}>
          <span className="text-sm text-[var(--lumi-text-primary)]">原文 → 译文交替</span>
          <Switch
            checked={bilingual}
            label="原文译文交替听读"
            onCheckedChange={(checked) => updateSettings({ speechBilingualAlternate: checked })}
          />
        </div>
        <div className={PANEL_ROW}>
          <span className="text-sm text-[var(--lumi-text-primary)]">原文译文间隔</span>
          <div
            role="group"
            aria-label="原文译文间隔"
            className="inline-flex gap-0.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-0.5"
          >
            {SPEECH_BILINGUAL_GAPS.map((gap) => (
              <button
                key={gap.key}
                type="button"
                aria-pressed={bilingualGap === gap.key}
                disabled={!bilingual}
                onClick={() => updateSettings({ speechBilingualGap: gap.key as SpeechBilingualGap })}
                className={cx(
                  'min-h-7 rounded-[var(--lumi-radius-sm)] px-1.5 text-xs transition-colors duration-[var(--lumi-motion-fast)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)] disabled:opacity-50',
                  bilingualGap === gap.key
                    ? 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-primary)]'
                    : 'text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)]',
                )}
              >
                {gap.label}
              </button>
            ))}
          </div>
        </div>
      </PanelSection>

      {/* N095 发音词典：只作用于出声/试听文本（文章 DOM 永不改写） */}
      <PanelSection
        title="发音词典"
        note={`朗读时按子串替换读音写法（大小写不敏感）；最多 ${SPEECH_LEXICON_CAP} 条，仅作用于朗读与试听。`}
      >
        {lexicon.length > 0 && (
          <ul className="flex flex-col gap-1">
            {lexicon.map((entry, index) => (
              <li
                key={`${entry.match}-${index}`}
                className="flex min-h-9 items-center gap-1.5 text-sm"
              >
                <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-primary)]">
                  {entry.match}
                </span>
                <span aria-hidden className="shrink-0 text-[var(--lumi-text-tertiary)]">
                  →
                </span>
                <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-secondary)]">
                  {entry.replace === '' ? '（静音删除）' : entry.replace}
                </span>
                <IconButton
                  size="sm"
                  icon={<X aria-hidden className="size-4" />}
                  label={`删除词典条目 ${entry.match}`}
                  touch
                  onClick={() => removeLexiconEntry(index)}
                />
              </li>
            ))}
          </ul>
        )}
        <div className="flex items-center gap-1.5">
          <input
            aria-label="词典匹配词"
            value={matchInput}
            placeholder="匹配词"
            onChange={(e) => {
              setMatchInput(e.target.value)
              setLexiconError(null)
            }}
            className="h-9 min-w-0 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-sm text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          />
          <input
            aria-label="替换为"
            value={replaceInput}
            placeholder="替换为"
            onChange={(e) => setReplaceInput(e.target.value)}
            className="h-9 min-w-0 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-sm text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          />
          <Button size="sm" variant="secondary" className="min-h-11" onClick={addLexiconEntry}>
            添加
          </Button>
        </div>
        {lexiconError !== null && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {lexiconError}
          </p>
        )}
      </PanelSection>

      {/* 试听文本：当前设置下真实将读的内容（含排除/词典/交替），首 300 字 */}
      <PanelSection
        title="试听文本"
        note="当前设置下将要朗读的内容预览（前 300 字）。"
      >
        {preview === null || preview.text === '' ? (
          <p className="text-xs text-[var(--lumi-text-tertiary)]">
            没有可朗读的正文（或全部被排除）。
          </p>
        ) : (
          <p
            data-lumi-speech-preview=""
            className="max-h-32 overflow-y-auto whitespace-pre-wrap rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-2 text-xs leading-5 text-[var(--lumi-text-secondary)]"
          >
            {preview.text}
            {preview.truncated ? '…' : ''}
          </p>
        )}
      </PanelSection>
    </div>
  )
}

/** F19/P18 朗读：桌面工具栏控件（移动端入口在「更多操作」菜单；语速
 * 分段与 P18 朗读设置面板是桌面专用，与既有行为一致）。面板触发按钮
 * 在朗读中以右上角 accent 圆点作微妙进行中指示（无动画，减少动效
 * 偏好天然满足）。 */
function SpeechToolbarControls({
  speech,
  bookmark,
  onSaveBookmark,
  collectBlocks,
}: {
  speech: ReturnType<typeof useSpeechControl>
  /** NF1 N092：听读书签（面板保存行 + 诚实反馈）。 */
  bookmark: SpeechBookmark | null
  onSaveBookmark: (blockIndex: number) => void
  /** NF1：试听文本与朗读同源的收集入口。 */
  collectBlocks?: () => SpeechCollection | null
}) {
  if (!speech.available) {
    return (
      <Tooltip content="此浏览器不支持语音朗读（speechSynthesis 不可用）">
        <IconButton
          icon={<Volume2 aria-hidden />}
          label="朗读"
          touch
          disabled
          title="此浏览器不支持语音朗读（speechSynthesis 不可用）"
        />
      </Tooltip>
    )
  }

  return (
    <>
      <Tooltip
        content={
          speech.state === 'idle' ? '朗读' : speech.state === 'speaking' ? '暂停朗读' : '继续朗读'
        }
      >
        <IconButton
          icon={
            speech.state === 'speaking' ? (
              <Pause aria-hidden />
            ) : speech.state === 'paused' ? (
              <Play aria-hidden />
            ) : (
              <Volume2 aria-hidden />
            )
          }
          label={
            speech.state === 'idle' ? '朗读' : speech.state === 'speaking' ? '暂停朗读' : '继续朗读'
          }
          aria-pressed={speech.state !== 'idle'}
          touch
          onClick={speech.toggle}
        />
      </Tooltip>
      {speech.state !== 'idle' && (
        <>
          <Tooltip content="停止朗读">
            <IconButton
              icon={<Square aria-hidden />}
              label="停止朗读"
              touch
              onClick={speech.stop}
            />
          </Tooltip>
          {/* 语速 segmented（0.75 / 1 / 1.25 / 1.5）；朗读中调速即重读当前段 */}
          <div
            role="group"
            aria-label="朗读语速"
            className="hidden items-center gap-0.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-0.5 lg:inline-flex"
          >
            {SPEECH_RATES.map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={speech.rate === value}
                onClick={() => speech.changeRate(value)}
                className={cx(
                  'min-h-8 min-w-11 rounded-[var(--lumi-radius-sm)] px-1 text-xs tabular-nums transition-colors duration-[var(--lumi-motion-fast)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                  speech.rate === value
                    ? 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-primary)]'
                    : 'text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)]',
                )}
              >
                {value}x
              </button>
            ))}
          </div>
        </>
      )}
      {/* P18 朗读设置面板：当前段进度/预览、声音挑选、语速、睡眠定时 */}
      <Popover
        width={320}
        trigger={({ triggerProps }) => (
          <Tooltip content="朗读设置">
            <IconButton
              {...triggerProps}
              icon={
                <span className="relative inline-flex">
                  <Volume2 aria-hidden />
                  {speech.state !== 'idle' && (
                    <span
                      aria-hidden
                      data-lumi-speaking-indicator=""
                      className="absolute -right-1 -top-0.5 size-1.5 rounded-full bg-[var(--lumi-accent-text)]"
                    />
                  )}
                </span>
              }
              label="朗读设置"
              touch
            />
          </Tooltip>
        )}
      >
        {() => (
          <SpeechPanelControls
            speech={speech}
            bookmark={bookmark}
            onSaveBookmark={onSaveBookmark}
            collectBlocks={collectBlocks}
          />
        )}
      </Popover>
    </>
  )
}

/** F21 分享动作状态（O127 hoist）：navigator.share 可用 → 系统分享
 * （AbortError=用户取消，静默）；其它错误 → 回退复制链接；无 share
 * 能力 → 直接复制链接。复制结果以工具栏旁即时文案反馈（成功「链接已
 * 复制」/失败可见），桌面按钮与移动端菜单项共享同一反馈。 */
function useShareAction(title: string, url: string | null) {
  const [feedback, setFeedback] = useState<string | null>(null)
  const canShare = typeof navigator !== 'undefined' && typeof navigator.share === 'function'
  const shareUrl = url ?? fallbackShareUrl()

  const showFeedback = (message: string) => {
    setFeedback(message)
    window.setTimeout(() => setFeedback((current) => (current === message ? null : current)), 2000)
  }

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl)
      showFeedback('链接已复制')
    } catch {
      showFeedback('复制失败')
    }
  }

  const run = async () => {
    if (canShare) {
      try {
        await navigator.share({ title, url: shareUrl })
        return
      } catch (error) {
        // AbortError = 用户取消分享系统面板，静默（不算失败）。
        if ((error as { name?: string } | null)?.name === 'AbortError') return
        // 其它错误 → 回退复制链接
      }
    }
    await copyLink()
  }

  return { canShare, feedback, run }
}

/** F21 分享：桌面工具栏按钮（移动端在「更多操作」菜单）。 */
function ShareToolbarButton({
  share,
}: {
  share: ReturnType<typeof useShareAction>
}) {
  return (
    <Tooltip content={share.canShare ? '分享' : '复制链接'}>
      <IconButton
        icon={<Share2 aria-hidden />}
        label={share.canShare ? '分享' : '复制链接'}
        touch
        onClick={() => {
          void share.run()
        }}
      />
    </Tooltip>
  )
}

/** F24 复制引用动作状态（O127 hoist）：无选区 = 标题+来源+链接；有选区
 * 附加引文（≤500 字）。两种格式（纯文本 / Markdown）二选一；成功短暂
 * Check 反馈；失败以只读文本框诚实降级（工具栏下方，两断点共用）。 */
function useQuoteCopyAction(title: string, source: string, url: string | null) {
  const [copiedRecently, setCopiedRecently] = useState(false)
  const [fallbackText, setFallbackText] = useState<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  const copy = async (format: 'plain' | 'markdown') => {
    const selection =
      typeof window.getSelection === 'function' ? window.getSelection()?.toString() ?? '' : ''
    const quote = selection.trim().slice(0, QUOTE_MAX_CHARS)
    const input = { title, source, url, quote }
    const text =
      format === 'plain' ? buildQuotePlainText(input) : buildQuoteMarkdownText(input)
    try {
      await navigator.clipboard.writeText(text)
      setFallbackText(null)
      setCopiedRecently(true)
      window.setTimeout(() => setCopiedRecently(false), 1200)
    } catch {
      setFallbackText(text)
    }
  }

  return { copiedRecently, fallbackText, textareaRef, copy }
}

/** F24 复制引用：桌面格式菜单（移动端为「更多操作」里的两个格式项）。 */
function QuoteToolbarMenu({
  quote,
}: {
  quote: ReturnType<typeof useQuoteCopyAction>
}) {
  return (
    <Menu
      trigger={({ triggerProps }) => (
        <Tooltip content="复制引用">
          <IconButton
            {...triggerProps}
            icon={
              quote.copiedRecently ? (
                <Check aria-hidden className="text-[var(--lumi-accent-text)]" />
              ) : (
                <Quote aria-hidden />
              )
            }
            label="复制引用"
            touch
          />
        </Tooltip>
      )}
      items={[
        { key: 'plain', content: '复制为纯文本' },
        { key: 'markdown', content: '复制为 Markdown' },
      ]}
      onSelect={(key) => {
        void quote.copy(key === 'markdown' ? 'markdown' : 'plain')
      }}
    />
  )
}

/** ReaderHeader — 标题 / 元信息 / 工具栏（0009 Gate 3 视觉重建）。
 *
 * 布局（Spec Task 12）：紧凑工具栏（IconButton 32px + Tooltip）+
 * 强标题（27px 级，Folo 实测锚点）+ 弱化元信息行。原 0006 的两个
 * 大按钮（标记已读/收藏）改为工具栏图标按钮——set 语义、共用
 * mutation 实例、pending 双禁用、key=entryRef 防泄漏等行为全部保留
 * （在 Reader.tsx 上挂 key）。
 *
 * 行为不变式（Spec 硬边界 3/5）：
 * - set 语义（PATCH 目标状态，非 toggle）；
 * - 打开原文只放行绝对 http/https（safeExternalHttpUrl），
 *   target=_blank + rel=noopener noreferrer。
 *
 * Reader 工具类功能（F13/F18/F19/F21/F22/F23/F24）挂同一工具栏：
 * 文内查找 / 朗读 / 分享 / 复制引用 / 打印 / 更多操作（自动滚屏、
 * 导出 Markdown、导出 HTML）。
 *
 * O127 移动端收纳（<lg）：高频动作留在工具栏（已读 / 稍后读 / 星标 /
 * 打开原文 / 语言视图 / AA），低频动作（快照 / AI 对话 / 查找 / 文中
 * 链接 / 朗读 / 分享 / 复制引用 / 打印）折进既有「更多操作」菜单。
 * 桌面用 `contents` 包装组保持平铺布局与顺序逐项不变（<lg 时该组
 * display:none）；「更多操作」菜单按断点增补菜单项（useIsMobile），
 * 两断点共享同一 hoisted 动作状态（快照/朗读/分享/引用）。
 *
 * P07：工具栏动作进注册表（lib/reader-toolbar.ts）——用户可通过
 * 「更多操作 → 自定义工具栏」按断点调序 / 显隐（设备本地持久化，
 * store/app-settings.ts 两键）；本组件只消费归一化后的序渲染，
 * 动作行为与 aria 标签逐字不变，已读 / 稍后读 / Aa / 标题元信息
 * 不在可配置范围。 */
/** Gate：语言视图三态控件（原文/双语/仅译文）。
 * 桌面 = 三段分段按钮；窄屏 = 紧凑 Menu（不遮挡/不挤出工具栏）。
 * 两态 Switch 表达不了三态，这里用显式的选项组。
 * P0-11：engine=browser 且浏览器不支持本地 Translator API 时整组
 * 禁用并给原因（不再让用户点开才发现不可用）；支持矩阵在设置页。 */
function LanguageViewControl({
  value,
  onChange,
  disabledReason,
}: {
  value: ReaderViewMode
  onChange: (mode: ReaderViewMode) => void
  /** 非 null = 当前引擎在此浏览器不可用（附原因），控件禁用。 */
  disabledReason?: string | null
}) {
  const options: { key: ReaderViewMode; label: string; short: string }[] = [
    { key: 'original', label: '原文', short: '原文' },
    { key: 'bilingual', label: '双语', short: '双语' },
    { key: 'translated', label: '仅译文', short: '译文' },
  ]
  const base =
    'inline-flex min-h-8 items-center gap-1 rounded-[var(--lumi-radius-md)] px-2 text-sm transition-colors duration-[var(--lumi-motion-fast)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]'
  const gated = disabledReason != null
  return (
    <>
      {/* 桌面分段 */}
      <div
        role="group"
        aria-label="语言视图"
        title={gated ? disabledReason : undefined}
        className="hidden items-center gap-0.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-0.5 lg:inline-flex"
      >
        {options.map((option) => (
          <button
            key={option.key}
            type="button"
            aria-pressed={value === option.key}
            disabled={gated && option.key !== 'original'}
            title={gated && option.key !== 'original' ? disabledReason : undefined}
            onClick={() => onChange(option.key)}
            className={cx(
              base,
              'min-w-0 px-2.5',
              value === option.key
                ? 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-primary)]'
                : 'text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)]',
              gated && option.key !== 'original' && 'opacity-50',
            )}
          >
            {option.key === 'translated' && (
              <Languages aria-hidden className="size-3.5" />
            )}
            {option.label}
          </button>
        ))}
      </div>
      {/* 移动端紧凑菜单 */}
      <div className="lg:hidden">
        <Menu
          trigger={({ triggerProps }) => (
            <Tooltip content={gated ? disabledReason : '语言视图'}>
              <IconButton
                {...triggerProps}
                icon={<Languages aria-hidden className={cx(value !== 'original' && 'text-[var(--lumi-accent-text)]')} />}
                label={
                  gated
                    ? `语言视图不可用：${disabledReason}`
                    : `语言视图：当前 ${options.find((o) => o.key === value)?.label ?? '原文'}`
                }
                touch
                disabled={gated}
              />
            </Tooltip>
          )}
          items={options.map((o) => ({
            key: o.key,
            content: value === o.key ? <strong>✓ {o.label}</strong> : o.label,
          }))}
          onSelect={(key) => onChange(key as ReaderViewMode)}
        />
      </div>
    </>
  )
}

export default function ReaderHeader({
  detail,
  viewMode = 'original',
  onViewModeChange,
  onOpenAiConversation,
  onOpenFind,
  onOpenLinks,
  collectSpeechBlocks,
  autoScrollState = 'off',
  onAutoScrollToggle,
  focusMode,
  onFocusModeChange,
}: {
  detail: EntryDetail
  /** Gate：语言视图（由 Reader 持有；工具栏与内容区共享同一状态）。 */
  viewMode?: ReaderViewMode
  onViewModeChange?: (mode: ReaderViewMode) => void
  /** 0016：打开文章限定 AI 对话（由 Reader 持有面板开关状态）。 */
  onOpenAiConversation?: () => void
  /** F13：打开文内查找（Reader 持有查找条状态）。 */
  onOpenFind?: () => void
  /** F054：文中链接清单（Reader 持有面板状态）。 */
  onOpenLinks?: () => void
  /** F19/P18：收集「从视口顶部段落开始」的朗读块（Reader 提供容器几何；
   * texts 下标即 DOM 块序，引擎逐块出声）。 */
  collectSpeechBlocks?: () => SpeechCollection | null
  /** F18：自动滚屏状态 + 切换（Reader 持有 rAF 循环）。 */
  autoScrollState?: AutoScrollState
  onAutoScrollToggle?: () => void
  /** 专注阅读（Reader 会话级状态，透传给 Aa 面板）。 */
  focusMode?: boolean
  onFocusModeChange?: (value: boolean) => void
}) {
  const mutation = useEntryStateMutation()
  const queryClient = useQueryClient()
  // F20：读/未读切换的短时撤销（撤销前核对服务器状态，防跨设备覆盖）
  const pushUndo = useUndo((s) => s.push)
  const { isReadLater, toggleReadLater, pendingFor, errorFor } = useToggleReadLater()
  const readLaterMarked = isReadLater(detail.entryRef)
  const readLaterPending = pendingFor(detail.entryRef)
  const readLaterError = errorFor(detail.entryRef)
  const showReadingTime = useAppSettings((s) => s.settings.readerShowReadingTime)
  // O127：移动端（<lg）低频动作收进「更多操作」菜单（jsdom 无
  // matchMedia → 视为移动端，与 useIsMobile 既有约定一致）。
  const isMobile = useIsMobile()
  // P07：工具栏排布——注册表 + 设备本地的两套归一化序决定「排布与显隐」，
  // 动作行为本身不变。桌面/移动端各自 resolve（隐藏的动作不渲染）。
  const storedDesktopOrder = useAppSettings((s) => s.settings.readerToolbarDesktopOrder)
  const storedMobileOrder = useAppSettings((s) => s.settings.readerToolbarMobileOrder)
  const desktopVisibleIds = resolveReaderToolbarVisible(storedDesktopOrder, 'desktop')
  const mobileVisibleIds = resolveReaderToolbarVisible(storedMobileOrder, 'mobile')
  // 移动端：primary 动作留工具栏，其余折进「更多操作」菜单（O127 语义）。
  const mobileInlineIds = mobileVisibleIds.filter((id) => readerToolbarAction(id).primary)
  const mobileMenuIds = mobileVisibleIds.filter((id) => !readerToolbarAction(id).primary)
  const [customizeOpen, setCustomizeOpen] = useState(false)
  // P16：导出到 Obsidian 对话框（与导出 Markdown/HTML 同一「更多操作」出口）。
  const [obsidianExportOpen, setObsidianExportOpen] = useState(false)
  // P0-11：本地引擎支持门控——engine=browser 且此浏览器没有 Translator
  // API（localTranslatorAvailable() 此前导出零调用）→ 控件禁用 + 原因。
  const aiSettings = useAiSettings()
  const translationDisabledReason =
    (aiSettings.data?.translationEngine ?? 'ai') === 'browser' && !localTranslatorAvailable()
      ? '此浏览器不支持本地翻译（需要 Chrome 内置 Translator API）；可在 设置 → 翻译 更换翻译引擎。'
      : null

  // url 与 contentHtml 一样来自外部 RSS，是不可信输入：
  // 只放行绝对 http/https，其余一律不渲染「打开原文」。
  const articleUrl = safeExternalHttpUrl(detail.url)
  const published = formatPublishedAt(detail.publishedAt)
  const pending = mutation.isPending

  // 0012 Gate 5：CJK 感知阅读时间（弱化展示；开关控制）。
  // 输入用 contentText（BFF 已产出的安全纯文本）优先，回退从
  // contentHtml 提取（本地 DOMParser，不进入渲染）。仅对不可信
  // HTML做只读解析，输出只有数字。文本量极小，不 memo。
  const readingTime = showReadingTime
    ? formatReadingTime(
        detail.contentText.trim() !== ''
          ? detail.contentText
          : textFromHtml(detail.contentHtml ?? ''),
      )
    : null

  // F22 导出输入：url 只放行 safeExternalHttpUrl 通过的地址（导出文件
  // 不携带不可信协议链接）；日期用已格式化的本地时间。
  const exportInput: ExportInput = {
    title: detail.title,
    source: detail.feedTitle,
    date: published,
    url: articleUrl,
    text: detail.contentText,
    html: detail.contentHtml ?? null,
  }

  // O127：低频动作状态 hoist——桌面控件与移动端菜单项共享。
  const snapshot = useSnapshotAction(articleUrl)
  const speech = useSpeechControl(collectSpeechBlocks)
  const share = useShareAction(detail.title, articleUrl)
  const quote = useQuoteCopyAction(detail.title, detail.feedTitle, articleUrl)

  // NF1 N092：听读分段书签（设备本地 lumi-speech-bookmarks，LRU 20）。
  // ReaderHeader 按 entryRef 重挂载——初始值即本篇书签；保存后同步刷新。
  const [speechBookmark, setSpeechBookmark] = useState<SpeechBookmark | null>(() =>
    getSpeechBookmark(detail.entryRef),
  )
  const [bookmarkChipDismissed, setBookmarkChipDismissed] = useState(false)
  const saveSpeechBookmarkForEntry = useCallback(
    (blockIndex: number) => {
      saveSpeechBookmark(detail.entryRef, blockIndex)
      setSpeechBookmark(getSpeechBookmark(detail.entryRef))
      setBookmarkChipDismissed(false)
    },
    // setState 稳定；编译器 lint 要求显式列入依赖。
    [detail.entryRef, setBookmarkChipDismissed],
  )

  /** 「更多操作」菜单项：移动端把非 primary 的可见动作按移动端序并入
      本菜单（O127 语义不变；quote 展开为纯文本/Markdown 两个格式项，
      朗读追加停止项——可用性门槛与既有条件一致）；两断点尾部固定
      自动滚屏 / 导出，最后是 P07「自定义工具栏」入口。 */
  const moreItems: MenuItemDef[] = []
  if (isMobile) {
    for (const id of mobileMenuIds) {
      switch (id) {
        case 'find':
          if (onOpenFind !== undefined) {
            moreItems.push({
              key: 'find',
              content: (
                <span className="flex items-center gap-2">
                  <Search aria-hidden className="size-4" />
                  文内查找
                </span>
              ),
            })
          }
          break
        case 'links':
          if (onOpenLinks !== undefined) {
            moreItems.push({
              key: 'links',
              content: (
                <span className="flex items-center gap-2">
                  <Link2 aria-hidden className="size-4" />
                  文中链接
                </span>
              ),
            })
          }
          break
        case 'ai':
          if (onOpenAiConversation !== undefined) {
            moreItems.push({
              key: 'ai',
              content: (
                <span className="flex items-center gap-2">
                  <MessageSquare aria-hidden className="size-4" />
                  AI 对话
                </span>
              ),
            })
          }
          break
        case 'snapshot':
          if (articleUrl !== null) {
            moreItems.push({
              key: 'snapshot',
              disabled: snapshot.pending,
              content: (
                <span className="flex items-center gap-2">
                  <Camera aria-hidden className="size-4" />
                  {snapshot.tooltip}
                </span>
              ),
            })
          }
          break
        case 'speech':
          if (collectSpeechBlocks !== undefined && speech.available) {
            const speechLabel =
              speech.state === 'idle' ? '朗读' : speech.state === 'speaking' ? '暂停朗读' : '继续朗读'
            moreItems.push({
              key: 'speech',
              content: (
                <span className="flex items-center gap-2">
                  {speech.state === 'speaking' ? (
                    <Pause aria-hidden className="size-4" />
                  ) : speech.state === 'paused' ? (
                    <Play aria-hidden className="size-4" />
                  ) : (
                    <Volume2 aria-hidden className="size-4" />
                  )}
                  {speechLabel}
                </span>
              ),
            })
            if (speech.state !== 'idle') {
              moreItems.push({
                key: 'speech-stop',
                content: (
                  <span className="flex items-center gap-2">
                    <Square aria-hidden className="size-4" />
                    停止朗读
                  </span>
                ),
              })
            }
          }
          break
        case 'share':
          moreItems.push({
            key: 'share',
            content: (
              <span className="flex items-center gap-2">
                <Share2 aria-hidden className="size-4" />
                {share.canShare ? '分享' : '复制链接'}
              </span>
            ),
          })
          break
        case 'quote':
          moreItems.push(
            {
              key: 'quote-plain',
              content: (
                <span className="flex items-center gap-2">
                  <Quote aria-hidden className="size-4" />
                  复制为纯文本
                </span>
              ),
            },
            {
              key: 'quote-markdown',
              content: (
                <span className="flex items-center gap-2">
                  <Quote aria-hidden className="size-4" />
                  复制为 Markdown
                </span>
              ),
            },
          )
          break
        case 'print':
          moreItems.push({
            key: 'print',
            content: (
              <span className="flex items-center gap-2">
                <Printer aria-hidden className="size-4" />
                打印
              </span>
            ),
          })
          break
        default:
          break
      }
    }
  }
  // F18/F22：自动滚屏 / 导出（原「更多操作」三项，两断点共有）。
  if (onAutoScrollToggle !== undefined) {
    moreItems.push({
      key: 'autoscroll',
      content: (
        <span className="flex items-center gap-2">
          {autoScrollState === 'off' ? (
            <Play aria-hidden className="size-4" />
          ) : (
            <Pause aria-hidden className="size-4" />
          )}
          {autoScrollState === 'off'
            ? '自动滚屏'
            : autoScrollState === 'running'
              ? '暂停自动滚屏'
              : '继续自动滚屏'}
        </span>
      ),
    })
  }
  moreItems.push(
    {
      key: 'export-md',
      content: (
        <span className="flex items-center gap-2">
          <FileText aria-hidden className="size-4" />
          导出 Markdown
        </span>
      ),
    },
    {
      key: 'export-html',
      content: (
        <span className="flex items-center gap-2">
          <FileCode aria-hidden className="size-4" />
          导出 HTML
        </span>
      ),
    },
  )
  // P16：导出到 Obsidian（选设备 → obsidian://new 交接；tooLong → 文件）。
  moreItems.push({
    key: 'export-obsidian',
    content: (
      <span className="flex items-center gap-2">
        <BookMarked aria-hidden className="size-4" />
        导出到 Obsidian
      </span>
    ),
  })
  // P07：工具栏自定义入口（两断点共有；「更多操作」锁定不可移除，
  // 入口恒可达）。
  moreItems.push({
    key: 'customize',
    content: (
      <span className="flex items-center gap-2">
        <Settings2 aria-hidden className="size-4" />
        自定义工具栏
      </span>
    ),
  })

  const handleMoreSelect = (key: string) => {
    if (key === 'find') {
      onOpenFind?.()
      return
    }
    if (key === 'links') {
      onOpenLinks?.()
      return
    }
    if (key === 'ai') {
      onOpenAiConversation?.()
      return
    }
    if (key === 'snapshot') {
      snapshot.save()
      return
    }
    if (key === 'speech') {
      speech.toggle()
      return
    }
    if (key === 'speech-stop') {
      speech.stop()
      return
    }
    if (key === 'share') {
      void share.run()
      return
    }
    if (key === 'quote-plain') {
      void quote.copy('plain')
      return
    }
    if (key === 'quote-markdown') {
      void quote.copy('markdown')
      return
    }
    if (key === 'print') {
      if (typeof window.print === 'function') window.print()
      return
    }
    if (key === 'autoscroll') {
      onAutoScrollToggle?.()
      return
    }
    if (key === 'export-md') {
      exportEntryAsMarkdown(exportInput)
      return
    }
    if (key === 'export-html') {
      exportEntryAsHtml(exportInput)
      return
    }
    if (key === 'export-obsidian') {
      setObsidianExportOpen(true)
      return
    }
    if (key === 'customize') {
      setCustomizeOpen(true)
    }
  }

  /** P07 inline 排布：桌面序是共享 DOM 的主干（一个 DOM 只能有一个
   * 顺序；两断点都 inline 的动作跟随桌面序落位）；桌面隐藏而移动端
   * inline 可见的动作追加在尾部。show 表达 CSS 折叠方向：
   * - 'desktop'：`contents max-lg:hidden`（<lg 折进「更多操作」菜单，
   *   按钮仍在 DOM——与 O127 折叠组一致，两断点共享 hoisted 状态）；
   * - 'mobile'：`hidden lg:contents`（仅 ≥lg 显示）。 */
  type InlineShow = 'both' | 'desktop' | 'mobile'
  const inlinePlan: { id: ReaderToolbarActionId; show: InlineShow }[] = desktopVisibleIds.map(
    (id) => ({
      id,
      show: mobileInlineIds.includes(id) ? ('both' as const) : ('desktop' as const),
    }),
  )
  for (const id of mobileInlineIds) {
    if (!desktopVisibleIds.includes(id)) inlinePlan.push({ id, show: 'mobile' })
  }

  /** 单个注册表动作的工具栏节点（可用性门槛与既有条件渲染一致；
   * 返回 null = 该动作当前不可用，不渲染）。 */
  const renderToolbarAction = (id: ReaderToolbarActionId): ReactNode => {
    switch (id) {
      case 'star':
        return pending ? (
          <IconButton
            icon={<Loader2 aria-hidden className="animate-spin" />}
            label="处理中"
            disabled
          />
        ) : (
          <Tooltip content={detail.starred ? '取消收藏' : '收藏'}>
            <IconButton
              icon={
                <Star
                  aria-hidden
                  className={cx(
                    detail.starred &&
                      'fill-[var(--lumi-category-orange)] text-[var(--lumi-category-orange)]',
                  )}
                />
              }
              label={detail.starred ? '取消收藏' : '收藏'}
              aria-pressed={detail.starred}
              touch
              onClick={() =>
                mutation.mutate({
                  entryRef: detail.entryRef,
                  patch: { starred: !detail.starred },
                })
              }
            />
          </Tooltip>
        )
      case 'open-original':
        // 只放行 safeExternalHttpUrl 通过的绝对 http/https（不可信输入）
        if (articleUrl === null) return null
        return (
          <a
            href={articleUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex min-h-8 items-center gap-1.5 whitespace-nowrap rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 text-sm text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            <ExternalLink aria-hidden className="size-3.5" />
            打开原文
          </a>
        )
      case 'snapshot':
        if (articleUrl === null) return null
        return <SaveSnapshotButton snapshot={snapshot} />
      case 'ai':
        if (onOpenAiConversation === undefined) return null
        return (
          <Tooltip content="AI 对话">
            <IconButton
              icon={<MessageSquare aria-hidden />}
              label="AI 对话"
              touch
              onClick={onOpenAiConversation}
            />
          </Tooltip>
        )
      case 'language':
        if (onViewModeChange === undefined) return null
        return (
          <LanguageViewControl
            value={viewMode ?? 'original'}
            onChange={onViewModeChange}
            disabledReason={translationDisabledReason}
          />
        )
      case 'find':
        if (onOpenFind === undefined) return null
        return (
          <Tooltip content="文内查找">
            <IconButton
              icon={<Search aria-hidden />}
              label="文内查找"
              touch
              onClick={onOpenFind}
            />
          </Tooltip>
        )
      case 'links':
        if (onOpenLinks === undefined) return null
        return (
          <Tooltip content="文中链接">
            <IconButton icon={<Link2 aria-hidden />} label="文中链接" touch onClick={onOpenLinks} />
          </Tooltip>
        )
      case 'speech':
        if (collectSpeechBlocks === undefined) return null
        return (
          <SpeechToolbarControls
            speech={speech}
            bookmark={speechBookmark}
            onSaveBookmark={saveSpeechBookmarkForEntry}
            collectBlocks={collectSpeechBlocks}
          />
        )
      case 'share':
        return <ShareToolbarButton share={share} />
      case 'quote':
        return <QuoteToolbarMenu quote={quote} />
      case 'print':
        return (
          <Tooltip content="打印">
            <IconButton
              icon={<Printer aria-hidden />}
              label="打印"
              touch
              onClick={() => {
                if (typeof window.print === 'function') window.print()
              }}
            />
          </Tooltip>
        )
      case 'more':
        if (!(onAutoScrollToggle !== undefined || isMobile)) return null
        return (
          <Menu
            trigger={({ triggerProps }) => (
              <Tooltip content="更多操作">
                <IconButton
                  {...triggerProps}
                  icon={<MoreHorizontal aria-hidden />}
                  label="更多操作"
                  touch
                />
              </Tooltip>
            )}
            items={moreItems}
            onSelect={handleMoreSelect}
          />
        )
    }
  }

  return (
    <>
      <header className="border-b border-[var(--lumi-separator)] pb-5">
      {/* 元信息行（弱化）：来源（P2：可点击进入该订阅范围）· 作者 ·
          时间 · 阅读时间。来源缺失降级「来源未知」。 */}
      <p className="flex min-w-0 flex-wrap items-center gap-x-1.5 text-xs text-[var(--lumi-text-tertiary)]">
        <SourceGlyph name={detail.feedTitle} />
        <SourceLabel
          feedTitle={detail.feedTitle}
          feedUrl={detail.feedUrl}
          className="min-w-0 max-w-[16rem] text-left"
        />
        {detail.author !== null && <span className="truncate">· {detail.author}</span>}
        {published !== '' && <span>· {published}</span>}
        {readingTime !== null && <span>· {readingTime}</span>}
      </p>

      {/* 强标题（Folo 锚点 27px/700；移动端略小） */}
      <h1 className="mt-2 text-[1.7rem] font-bold leading-snug text-[var(--lumi-text-primary)] max-lg:text-2xl max-lg:leading-tight">
        {detail.title}
      </h1>

      {/* 工具栏：紧凑图标按钮（桌面 32px，手机 touch 44px）。
          pending 时统一转圈，双按钮禁用（同一篇同时最多一个 PATCH）。
          O127：移动端高频动作保留（已读/稍后读/星标/打开原文/语言视图/
          AA/更多），低频动作两组 `contents max-lg:hidden` 折进「更多」
          菜单——`lg:contents` 使桌面 DOM 平铺顺序与旧版逐项一致。 */}
      <div className="mt-4 flex flex-wrap items-center gap-1 lg:gap-1.5">
        {pending ? (
          <IconButton
            icon={<Loader2 aria-hidden className="animate-spin" />}
            label="处理中"
            disabled
          />
        ) : (
          <Tooltip content={detail.read ? '标记为未读' : '标记为已读'}>
            <IconButton
              icon={
                <Check
                  aria-hidden
                  className={cx(
                    detail.read
                      ? 'text-[var(--lumi-accent-text)]'
                      : 'text-current',
                  )}
                />
              }
              label={detail.read ? '标记为未读' : '标记为已读'}
              aria-pressed={detail.read}
              touch
              onClick={() => {
                const next = !detail.read
                mutation.mutate(
                  { entryRef: detail.entryRef, patch: { read: next } },
                  {
                    onSuccess: () => {
                      // F20：8 秒撤销窗口；撤销前核对服务器 read 状态
                      pushUndo({
                        label: next ? '已标记已读' : '已标记未读',
                        check: async () => {
                          const fresh = await queryClient.fetchQuery({
                            queryKey: ['entry', detail.entryRef],
                            queryFn: ({ signal }) => getEntry(detail.entryRef, signal),
                            staleTime: 0,
                          })
                          return fresh.read === next
                        },
                        undo: async () => {
                          await mutation.mutateAsync({
                            entryRef: detail.entryRef,
                            patch: { read: !next },
                          })
                        },
                      })
                    },
                  },
                )
              }}
            />
          </Tooltip>
        )}

        {/* 稍后读（P0-01）：服务端保留工作区成员（真源）——乐观切换 +
            失败回滚由 useReadLaterMemberMutation 承载；✓ ◷ ☆ 顺序——
            阅读处理 → 临时保存 → 长期收藏；active = accent icon，同一
            Clock 图标不换形（§23）；失败行内诚实提示（不假装成功）。 */}
        <Tooltip content={readLaterMarked ? '从稍后读移除' : '加入稍后读'}>
          <IconButton
            icon={
              readLaterPending ? (
                <Loader2 aria-hidden className="animate-spin" />
              ) : (
                <Clock
                  aria-hidden
                  className={cx(
                    readLaterMarked && 'fill-[var(--lumi-accent-soft)]',
                  )}
                />
              )
            }
            label={readLaterMarked ? '从稍后读移除' : '加入稍后读'}
            aria-pressed={readLaterMarked}
            touch
            disabled={readLaterPending}
            className={readLaterMarked ? 'text-[var(--lumi-accent-text)]' : undefined}
            onClick={() => toggleReadLater(detail.entryRef)}
          />
        </Tooltip>
        {readLaterError !== null && (
          <span role="alert" className="text-xs text-[var(--lumi-danger)]">
            稍后读操作失败：{readLaterError instanceof Error ? readLaterError.message : '请稍后重试。'}
          </span>
        )}

        {/* P07：注册表驱动的工具栏排布。可见动作按桌面序落位（共享 DOM
            只能有一个顺序，两断点都 inline 的动作跟随桌面序）；非移动端
            inline 动作包 `contents max-lg:hidden`（<lg 折进「更多操作」
            菜单，按钮仍在 DOM——两断点共享同一 hoisted 状态，与 O127
            一致）；仅移动端 inline 的动作包 `hidden lg:contents`。
            「更多操作」是锁定动作，按序渲染在自身位置；已读 / 稍后读 /
            Aa 面板与标题元信息块不在注册表内（恒展示）。 */}
        {inlinePlan.map(({ id, show }) => {
          const node = renderToolbarAction(id)
          if (node === null) return null
          if (show === 'both') return <Fragment key={id}>{node}</Fragment>
          return (
            <div
              key={id}
              className={show === 'desktop' ? 'contents max-lg:hidden' : 'hidden lg:contents'}
            >
              {node}
            </div>
          )
        })}

        {/* 0012 Gate 7：Reader 内快速阅读样式面板（Aa）；与设置中心
            同一 settings source，不遮挡正文关键操作。F15/F17/专注：
            代码换行 / 按屏翻页 / 专注阅读开关挂同一面板。 */}
        <ReaderAaPanel focusMode={focusMode} onFocusModeChange={onFocusModeChange} />

        {/* F19 朗读错误（两断点共用：移动端入口在菜单里，错误仍在
            工具栏行内诚实透出） */}
        {speech.error !== null && (
          <span role="alert" className="text-xs text-[var(--lumi-danger)]">
            {speech.error}
          </span>
        )}

        {/* F21 分享反馈（hoisted：桌面按钮 / 移动菜单共用，占整行防挤压） */}
        {share.feedback !== null && (
          <span
            aria-live="polite"
            data-lumi-share-feedback=""
            className="w-full basis-full text-xs text-[var(--lumi-accent-text)]"
          >
            {share.feedback}
          </span>
        )}

        {/* F24 复制引用失败：只读文本框诚实降级（两断点共用） */}
        {quote.fallbackText !== null && (
          <div className="flex w-full basis-full items-start gap-2" data-lumi-quote-fallback="">
            <textarea
              ref={quote.textareaRef}
              readOnly
              value={quote.fallbackText}
              aria-label="复制失败的引用文本（可手动复制）"
              rows={4}
              className="w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-2 text-sm text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
            />
            <Button size="sm" onClick={() => quote.textareaRef.current?.select()}>
              全选
            </Button>
          </div>
        )}
      </div>

      {mutation.isError && (
        <p className="mt-2 text-sm text-[var(--lumi-danger)]" role="alert">
          状态更新失败：{mutation.error instanceof Error ? mutation.error.message : '请稍后重试。'}
        </p>
      )}
      </header>

      {/* P07：自定义工具栏对话框（Escape / 焦点陷阱 / 滚动锁由 Dialog
          原语承载；保存写回 app-settings 的设备本地两键）。仅打开时
          挂载——工作副本以 store 当前值初始化，关闭即丢弃。 */}
      {customizeOpen && (
        <ReaderToolbarCustomizeDialog
          open
          onClose={() => setCustomizeOpen(false)}
        />
      )}

      {/* P16：导出到 Obsidian（选设备档案 → 服务端渲染模板 + URI/file 裁决）。
          仅打开时挂载——设备列表查询不随阅读页空跑；实现走懒 chunk。 */}
      {obsidianExportOpen && (
        <Suspense fallback={null}>
          <ObsidianExportDialog
            open
            detail={detail}
            onClose={() => setObsidianExportOpen(false)}
          />
        </Suspense>
      )}

      {/* NF1 N091：「从此处朗读」选区浮动入口。speechSynthesis 可用且正文
          收集可用才挂载；点击从选中所在块开始朗读（引擎 cancel-first，
          既有播放自动停止）；代码/表格与被排除块内的选区不显示入口。 */}
      {speech.available && collectSpeechBlocks !== undefined && (
        <SpeechSelectionLayer
          getBlocks={collectSpeechBlocks}
          onSpeakFromBlock={speech.speakFromBlock}
        />
      )}

      {/* NF1 N092：续听 chip——本篇有听读书签且未在朗读时出现。点击从
          保存的段开头继续（浏览器语音无法句中定位——诚实按段续读，
          title 有说明）。×只隐藏本会话提示，不清除书签。 */}
      {speech.available &&
        speechBookmark !== null &&
        speech.state === 'idle' &&
        !bookmarkChipDismissed && (
          <div
            data-lumi-speech-bookmark-chip=""
            className="fixed bottom-6 left-4 z-10 flex max-w-[calc(100%-2rem)] items-center gap-1.5 rounded-full border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] py-1 pe-1.5 ps-3 shadow-[var(--lumi-shadow-popover)] print:hidden"
          >
            <span className="whitespace-nowrap text-xs text-[var(--lumi-text-secondary)]">
              听读书签
            </span>
            <Button
              size="sm"
              variant="primary"
              className="min-h-11 rounded-full"
              title="按段续读：从该段开头朗读（浏览器语音无法在句中定位）"
              onClick={() => speech.speakFromBlock(speechBookmark.blockIndex)}
            >
              从第 {speechBookmark.blockIndex + 1} 段继续朗读
            </Button>
            <IconButton
              size="sm"
              icon={<X aria-hidden className="size-4" />}
              label="隐藏续读提示"
              touch
              onClick={() => setBookmarkChipDismissed(true)}
            />
          </div>
        )}
    </>
  )
}
