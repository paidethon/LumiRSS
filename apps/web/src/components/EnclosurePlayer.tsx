/** F011 enclosure 播放器 —— Reader 顶部的 audio/video 附件播放。
 *
 * 语义：显式用户点击才开始（禁止 autoplay）；倍速 0.75/1/1.25/1.5/2；
 * 上次播放位置续播（localStorage 有界记录：仅保留最近 50 条，
 * key = lumirss-enclosure-positions）。
 * N100 播放故障自助诊断：失败按 {网络失败 / 解码失败 / 音源缺失 /
 * 未授权} 分型，各自给匹配处置——网络失败允许一次手动重试（有界，
 * 绝不自动循环）；解码失败有备选音源时切换、否则诚实死路；音源缺失
 * 与未授权给设置/重新登录指引。 */

import { useEffect, useMemo, useRef, useState } from 'react'

import { isPlayableEnclosure } from '../lib/enclosure'

export { isPlayableEnclosure }
import {
  AlertCircle,
  Play,
  RotateCcw,
  ShieldAlert,
  Unplug,
} from 'lucide-react'
import {
  classifyMediaErrorCode,
  probePlaybackSource,
  type PlaybackFailure,
} from '../lib/playback-diagnostics'
import { Button } from './ui/Button'
import { cx } from './ui/cx'

export const ENCLOSURE_POSITIONS_KEY = 'lumirss-enclosure-positions'
export const ENCLOSURE_POSITIONS_LIMIT = 50
export const PLAYBACK_RATES = [0.75, 1, 1.25, 1.5, 2] as const
export type PlaybackRate = (typeof PLAYBACK_RATES)[number]
/** N100：网络失败允许的手动重试上限（1 次）——之后诚实死路，绝不
 * 无限重试循环。 */
export const ENCLOSURE_RETRY_BUDGET = 1

export interface EnclosureItem {
  href: string
  type?: string | null
}

type PositionMap = Record<string, number>

/** 读取续播位置表（corrupted → {}）。 */
export function readEnclosurePositions(
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): PositionMap {
  if (storage === null) return {}
  try {
    const raw = storage.getItem(ENCLOSURE_POSITIONS_KEY)
    if (raw === null) return {}
    const parsed: unknown = JSON.parse(raw)
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    const out: PositionMap = {}
    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof value === 'number' && Number.isFinite(value) && value >= 0) {
        out[key] = value
      }
    }
    return out
  } catch {
    return {}
  }
}

/** 记录播放位置（写入序近似 LRU：重写 key 移到末尾；超过 50 条逐出最旧）。 */
export function recordEnclosurePosition(
  id: string,
  seconds: number,
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): void {
  if (storage === null) return
  try {
    const positions = readEnclosurePositions(storage)
    delete positions[id]
    positions[id] = Math.max(0, seconds)
    const entries = Object.entries(positions)
    const bounded = entries.slice(Math.max(0, entries.length - ENCLOSURE_POSITIONS_LIMIT))
    storage.setItem(ENCLOSURE_POSITIONS_KEY, JSON.stringify(Object.fromEntries(bounded)))
  } catch {
    // 写失败静默：续播是本地增强数据
  }
}

// isPlayableEnclosure 移至 lib/enclosure（Reader 首屏只需谓词，不必
// 拖入整个播放器模块）；此处 re-export 兼容既有引用与测试。

/** 单个附件播放器（显式开始；倍速；续播；N100 分型错误态 + 匹配处置）。
 * `alternatives` 为可选备选音源清单（同一条目的其它编码/码率）——解码
 * 失败时提供「换源」；没有备选则诚实死路。 */
export function EnclosurePlayer({
  enclosure,
  entryRef,
  storage = typeof localStorage === 'undefined' ? null : localStorage,
  alternatives = [],
  onSwitchAlternative,
}: {
  enclosure: EnclosureItem
  entryRef: string
  storage?: Storage | null
  /** N100：备选音源（不含当前）；解码失败且存在备选时出现「换源」。 */
  alternatives?: EnclosureItem[]
  /** N100：换源回调（父组件替换 enclosure；缺省 = 无备选可用）。 */
  onSwitchAlternative?: (next: EnclosureItem) => void
}) {
  const [started, setStarted] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [retriesUsed, setRetriesUsed] = useState(0)
  const [failure, setFailure] = useState<PlaybackFailure | null>(null)
  const [rate, setRate] = useState<PlaybackRate>(1)
  const mediaRef = useRef<HTMLAudioElement | HTMLVideoElement | null>(null)
  const positionId = useMemo(() => `${entryRef}|${enclosure.href}`, [entryRef, enclosure.href])
  const isVideo = (enclosure.type ?? '').toLowerCase().startsWith('video/')
  const hasSource = (enclosure.href ?? '').trim() !== ''

  // 显式开始后：恢复上次位置 + 倍速 + 进度记录
  useEffect(() => {
    if (!started || !hasSource) return
    const media = mediaRef.current
    if (media === null) return
    const saved = readEnclosurePositions(storage)[positionId] ?? 0
    const onLoaded = () => {
      if (saved > 5 && Number.isFinite(media.duration) && saved < media.duration - 2) {
        media.currentTime = saved
      }
    }
    const onTimeUpdate = () => {
      if (!media.paused) recordEnclosurePosition(positionId, media.currentTime, storage)
    }
    // N100：media error → 错误码分型 + 一次有界同源探测（区分未授权 /
    // 音源缺失 / 解码失败）。探测不重试；跨源地址诚实跳过探测（结果
    // 不可信），保持错误码分型。
    const onError = () => {
      setFailure(importPlaybackFailure(classifyMediaErrorCode(media.error?.code ?? null).cls))
      void probePlaybackSource(enclosure.href).then((probed) => {
        if (probed !== null) setFailure(importPlaybackFailure(probed))
      })
    }
    media.addEventListener('loadedmetadata', onLoaded)
    media.addEventListener('timeupdate', onTimeUpdate)
    media.addEventListener('error', onError)
    media.playbackRate = rate
    return () => {
      media.removeEventListener('loadedmetadata', onLoaded)
      media.removeEventListener('timeupdate', onTimeUpdate)
      media.removeEventListener('error', onError)
    }
  }, [started, positionId, storage, rate, attempt, hasSource, enclosure.href])

  useEffect(() => {
    const media = mediaRef.current
    if (media !== null) media.playbackRate = rate
  }, [rate])

  if (!started) {
    return (
      <div
        data-testid="enclosure-player"
        className="flex flex-wrap items-center gap-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2.5"
      >
        <Button
          size="sm"
          variant="primary"
          disabled={!hasSource}
          onClick={() => {
            setFailure(null)
            setRetriesUsed(0)
            setStarted(true)
          }}
          aria-label={hasSource ? `播放附件 ${enclosure.href}` : '附件没有可用音源'}
        >
          <Play aria-hidden className="size-4" />
          播放
        </Button>
        <span className="min-w-0 flex-1 truncate text-xs text-[var(--lumi-text-secondary)]" title={enclosure.href}>
          {enclosure.type ?? '媒体附件'} · {enclosure.href !== '' ? enclosure.href : '（无附件地址）'}
        </span>
      </div>
    )
  }

  if (failure !== null) {
    return (
      <FailurePanel
        failure={failure}
        retriesUsed={retriesUsed}
        canSwitchAlternative={failure.cls === 'decode' && alternatives.length > 0 && onSwitchAlternative !== undefined}
        onRetryNetwork={() => {
          // N100：网络失败的有界手动重试——预算用尽后按钮不再出现。
          setRetriesUsed((n) => n + 1)
          setFailure(null)
          setAttempt((n) => n + 1)
        }}
        onSwitchAlternative={() => {
          const next = alternatives[0]
          if (next !== undefined && onSwitchAlternative !== undefined) {
            setFailure(null)
            setRetriesUsed(0)
            onSwitchAlternative(next)
          }
        }}
        onRestartFresh={() => {
          // 未授权：重新登录后的干净起点（回到初始播放按钮，非自动重试）。
          setFailure(null)
          setStarted(false)
        }}
      />
    )
  }

  // 音源缺失：地址为空的附件点「播放」直接给诊断（无重试——重试无意义）
  if (!hasSource) {
    return (
      <FailurePanel
        failure={{
          cls: 'missing',
          message: '音源缺失：附件地址为空或已失效。',
          hint: '请检查订阅来源的附件设置，或稍后等文章更新。',
        }}
        retriesUsed={0}
        canSwitchAlternative={false}
        onRetryNetwork={() => undefined}
        onSwitchAlternative={() => undefined}
        onRestartFresh={() => setStarted(false)}
      />
    )
  }

  const mediaProps = {
    ref: mediaRef as never,
    src: enclosure.href,
    controls: true,
    preload: 'metadata' as const,
    // 禁止 autoplay：播放由用户点击「播放」后的原生控件/初始 play 承担
    autoPlay: false,
    className: 'w-full',
    'data-testid': 'enclosure-media',
  }

  return (
    <div
      data-testid="enclosure-player"
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
    >
      {isVideo ? <video {...mediaProps} /> : <audio {...mediaProps} />}
      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="播放速度">
        <span className="text-xs text-[var(--lumi-text-tertiary)]">倍速</span>
        {PLAYBACK_RATES.map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={rate === value}
            onClick={() => setRate(value)}
            className={cx(
              'min-h-11 rounded-[var(--lumi-radius-md)] px-2 py-1 text-xs',
              rate === value
                ? 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]'
                : 'text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]',
            )}
          >
            {value}x
          </button>
        ))}
      </div>
    </div>
  )
}

/** 探测结果 → 展示用 PlaybackFailure（保持诊断文案单一来源）。 */
function importPlaybackFailure(cls: PlaybackFailure['cls']): PlaybackFailure {
  switch (cls) {
    case 'unauthorized':
      return { cls, message: '未授权：音源要求登录（401/403）。', hint: '登录状态可能已过期，请重新登录后再试。' }
    case 'missing':
      return { cls, message: '音源缺失：附件地址已失效（404）。', hint: '请检查订阅来源的附件设置，或稍后等文章更新。' }
    case 'decode':
      return { cls, message: '解码失败：音频数据无法在此浏览器播放（格式可能不受支持）。', hint: '可尝试其它音源；没有备选时该附件无法播放。' }
    case 'network':
      return { cls, message: '网络失败：无法下载音频数据。', hint: '请检查网络后重试。' }
    default:
      return { cls, message: '播放失败：原因未分类。', hint: '请稍后重试；持续失败请检查附件地址与网络。' }
  }
}

/** N100 分型失败面板：诊断文案 + 匹配处置（每类只有自己的动作）。 */
function FailurePanel({
  failure,
  retriesUsed,
  canSwitchAlternative,
  onRetryNetwork,
  onSwitchAlternative,
  onRestartFresh,
}: {
  failure: PlaybackFailure
  retriesUsed: number
  canSwitchAlternative: boolean
  onRetryNetwork: () => void
  onSwitchAlternative: () => void
  onRestartFresh: () => void
}) {
  const retryAvailable = failure.cls === 'network' && retriesUsed < ENCLOSURE_RETRY_BUDGET
  return (
    <div
      data-testid="enclosure-player"
      data-lumi-failure-class={failure.cls}
      className="flex flex-wrap items-center gap-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-danger)]/30 bg-[var(--lumi-danger)]/10 px-3 py-2.5"
    >
      {failure.cls === 'unauthorized' ? (
        <ShieldAlert aria-hidden className="size-4 shrink-0 text-[var(--lumi-danger)]" />
      ) : failure.cls === 'missing' ? (
        <Unplug aria-hidden className="size-4 shrink-0 text-[var(--lumi-danger)]" />
      ) : (
        <AlertCircle aria-hidden className="size-4 shrink-0 text-[var(--lumi-danger)]" />
      )}
      <span className="min-w-0 flex-1 text-xs text-[var(--lumi-danger)]">
        {failure.message}
        {failure.hint !== '' ? ` ${failure.hint}` : ''}
        {failure.cls === 'network' && retriesUsed >= ENCLOSURE_RETRY_BUDGET
          ? ' 已重试一次仍失败——请稍后再试。'
          : ''}
      </span>
      {retryAvailable && (
        <Button size="sm" variant="secondary" onClick={onRetryNetwork}>
          <RotateCcw aria-hidden className="size-3.5" />
          重试
        </Button>
      )}
      {canSwitchAlternative && (
        <Button size="sm" variant="secondary" onClick={onSwitchAlternative}>
          换其它音源
        </Button>
      )}
      {failure.cls === 'unauthorized' && (
        <Button size="sm" variant="secondary" onClick={onRestartFresh}>
          已重新登录？重新开始
        </Button>
      )}
    </div>
  )
}
