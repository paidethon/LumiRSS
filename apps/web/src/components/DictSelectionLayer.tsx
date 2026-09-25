/** DictSelectionLayer — N069 选词词典卡（浮动入口，web-only）。
 *
 * 交互形态与 SpeechSelectionLayer 同一模式：监听正文内的文本选区，
 * 选中的是**单个词**（normalizeDictWord：多词不弹卡）时在选区末端显示
 * 词典卡（词 + 查询 + 发音）。查询走用户在 设置 → 阅读 配置的词典 API
 * 模板（{word} 占位符）：
 * - 未配置 → 卡片诚实显示「未配置词典来源」+ 设置路径提示，零请求；
 * - 离线（navigator.onLine=false）→ 「本机离线：无可用词典」，零请求；
 * - 已配置在线 → 请求只携带单词本身（URL 模板替换），展示词头/音标/
 *   释义/来源主机；结构化提取失败回退原始片段（诚实截断）。
 * 发音复用 P18 朗读链路（speakText：pickVoice 中文优先，语速取设置）。
 *
 * 定位用选区 getBoundingClientRect（jsdom 全 0 时行为可测、定位降级）；
 * mousedown preventDefault 维持选区（与批注/朗读浮动条同一交互形态）。 */

import { useCallback, useEffect, useState } from 'react'
import { useAppSettings } from '../store/app-settings'
import {
  DICT_OFFLINE_HINT,
  DICT_SETUP_HINT,
  normalizeDictWord,
  queryDict,
  type DictEntry,
} from '../lib/dict-lookup'
import { speakText, speechSynthesisAvailable } from '../lib/reader-speech'
import { IconButton } from './ui/IconButton'
import { X } from 'lucide-react'
import { cx } from './ui/cx'

interface DictTarget {
  word: string
  x: number
  y: number
}

type DictCardState =
  | { phase: 'idle' }
  | { phase: 'loading' }
  | { phase: 'unconfigured' }
  | { phase: 'offline' }
  | { phase: 'error'; message: string }
  | { phase: 'done'; entry: DictEntry; raw?: string }

/** 单一状态对象：选区目标 + 卡片内容。update 对「同一目标」是 no-op——
 * selectionchange 在部分环境会异步补发，重置卡片会把查询结果闪回空卡。 */
interface DictLayerState {
  target: DictTarget | null
  card: DictCardState
}

const IDLE_CARD: DictCardState = { phase: 'idle' }

export function DictSelectionLayer() {
  const [state, setState] = useState<DictLayerState>({ target: null, card: IDLE_CARD })

  const update = useCallback(() => {
    const sel = window.getSelection()
    if (
      sel === null ||
      sel.rangeCount === 0 ||
      sel.isCollapsed ||
      typeof sel.getRangeAt !== 'function'
    ) {
      setState((prev) => (prev.target === null ? prev : { target: null, card: IDLE_CARD }))
      return
    }
    const container = document.querySelector('.lumi-reader-article')
    if (container === null) {
      setState((prev) => (prev.target === null ? prev : { target: null, card: IDLE_CARD }))
      return
    }
    const range = sel.getRangeAt(0)
    const common = range.commonAncestorContainer
    const el = common.nodeType === Node.ELEMENT_NODE ? (common as Element) : common.parentElement
    if (el === null || !container.contains(el)) {
      setState((prev) => (prev.target === null ? prev : { target: null, card: IDLE_CARD }))
      return
    }
    const word = normalizeDictWord(range.toString())
    if (word === null) {
      setState((prev) => (prev.target === null ? prev : { target: null, card: IDLE_CARD }))
      return
    }
    const rect =
      typeof range.getBoundingClientRect === 'function'
        ? range.getBoundingClientRect()
        : { left: 0, top: 0, right: 0, bottom: 0 }
    const next: DictTarget = { word, x: rect.left, y: rect.bottom }
    setState((prev) => {
      const cur = prev.target
      if (
        cur !== null &&
        cur.word === next.word &&
        cur.x === next.x &&
        cur.y === next.y
      ) {
        return prev // 同一目标：保留卡片状态（防 selectionchange 补发闪回）
      }
      return { target: next, card: IDLE_CARD }
    })
  }, [])

  useEffect(() => {
    const onMouseUp = () => update()
    const container = document.querySelector('.lumi-reader-article')
    document.addEventListener('selectionchange', update)
    container?.addEventListener('mouseup', onMouseUp)
    container?.addEventListener('touchend', onMouseUp)
    // 挂载时同步一次（lazy 分包晚于用户选区就绪的场景：已有合法选区
    // 则直接出卡；无选区/多词自然为无卡）。
    update()
    return () => {
      document.removeEventListener('selectionchange', update)
      container?.removeEventListener('mouseup', onMouseUp)
      container?.removeEventListener('touchend', onMouseUp)
    }
  }, [update])

  const runQuery = () => {
    if (state.target === null) return
    const template = useAppSettings.getState().settings.dictApiUrl
    // 离线 / 未配置：不发请求，诚实提示（组件本地判定与 lib 双保险）
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      setState((prev) => ({ ...prev, card: { phase: 'offline' } }))
      return
    }
    if (template === '') {
      setState((prev) => ({ ...prev, card: { phase: 'unconfigured' } }))
      return
    }
    setState((prev) => ({ ...prev, card: { phase: 'loading' } }))
    void queryDict(template, state.target.word, { online: true }).then((result) => {
      setState((prev) => {
        if (prev.target === null) return prev
        if (result.status === 'done') {
          return { ...prev, card: { phase: 'done', entry: result.entry, raw: result.raw } }
        }
        if (result.status === 'offline') return { ...prev, card: { phase: 'offline' } }
        if (result.status === 'unconfigured') return { ...prev, card: { phase: 'unconfigured' } }
        return { ...prev, card: { phase: 'error', message: result.message } }
      })
    })
  }

  const speak = () => {
    if (state.target === null) return
    const s = useAppSettings.getState().settings
    speakText(state.target.word, { rate: s.speechRate })
  }

  if (state.target === null) return null

  const target = state.target
  const card = state.card

  const canSpeak = speechSynthesisAvailable()

  return (
    <div
      data-lumi-dict-card=""
      className="fixed z-40 print:hidden"
      style={{ top: Math.max(0, target.y + 6), left: Math.max(0, target.x) }}
    >
      <div
        role="dialog"
        aria-label={`词典卡：${target.word}`}
        className={cx(
          'w-72 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)]',
          'bg-[var(--lumi-surface-elevated)] p-3 shadow-[var(--lumi-shadow-popover)]',
        )}
        onMouseDown={(event) => event.preventDefault()}
      >
        <div className="flex items-center gap-1">
          <span data-testid="dict-word" className="min-w-0 flex-1 truncate text-sm font-medium text-[var(--lumi-text-primary)]">
            {target.word}
          </span>
          {canSpeak && (
            <button
              type="button"
              data-testid="dict-speak"
              onClick={speak}
              className="min-h-11 min-w-11 rounded-[var(--lumi-radius-md)] px-2 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
            >
              发音
            </button>
          )}
          <IconButton
            size="sm"
            icon={<X aria-hidden className="size-4" />}
            label="关闭词典卡"
            touch
            onClick={() => setState({ target: null, card: IDLE_CARD })}
          />
        </div>

        {card.phase === 'idle' && (
          <button
            type="button"
            data-testid="dict-query"
            onClick={runQuery}
            className="mt-2 inline-flex min-h-11 w-full items-center justify-center rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-sm text-[var(--lumi-text-primary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            查询
          </button>
        )}
        {card.phase === 'loading' && (
          <p role="status" data-testid="dict-loading" className="mt-2 text-xs text-[var(--lumi-text-secondary)]">
            查询中…
          </p>
        )}
        {card.phase === 'unconfigured' && (
          <p role="status" data-testid="dict-unconfigured" className="mt-2 text-xs leading-5 text-[var(--lumi-text-secondary)]">
            未配置词典来源。
            <br />
            {DICT_SETUP_HINT}
          </p>
        )}
        {card.phase === 'offline' && (
          <p role="status" data-testid="dict-offline" className="mt-2 text-xs leading-5 text-[var(--lumi-text-secondary)]">
            本机离线：无可用词典。
            <br />
            {DICT_OFFLINE_HINT}
          </p>
        )}
        {card.phase === 'error' && (
          <p role="alert" data-testid="dict-error" className="mt-2 text-xs text-[var(--lumi-danger)]">
            {card.message}
          </p>
        )}
        {card.phase === 'done' && (
          <div data-testid="dict-result" className="mt-2 flex flex-col gap-1.5 text-xs leading-5">
            {card.entry.phonetic !== null && (
              <p className="text-[var(--lumi-text-tertiary)]">{card.entry.phonetic}</p>
            )}
            {card.entry.term !== null && card.entry.term !== target.word && (
              <p className="text-[var(--lumi-text-secondary)]">词头：{card.entry.term}</p>
            )}
            {card.entry.meanings.length > 0 ? (
              <ul className="flex list-disc flex-col gap-0.5 ps-4 text-[var(--lumi-text-primary)]">
                {card.entry.meanings.map((meaning, index) => (
                  <li key={index}>{meaning}</li>
                ))}
              </ul>
            ) : card.raw !== undefined ? (
              <p className="whitespace-pre-wrap text-[var(--lumi-text-secondary)]">
                {card.raw}
              </p>
            ) : (
              <p className="text-[var(--lumi-text-tertiary)]">词典未返回释义。</p>
            )}
            {card.entry.source !== '' && (
              <p className="text-[var(--lumi-text-tertiary)]">来源：{card.entry.source}（仅发送了所选单词）</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default DictSelectionLayer
