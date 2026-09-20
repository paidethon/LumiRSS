/** F011 enclosure 播放器 —— Reader 顶部的 audio/video 附件播放。
 *
 * 语义：显式用户点击才开始（禁止 autoplay）；倍速 0.75/1/1.25/1.5/2；
 * 上次播放位置续播（localStorage 有界记录：仅保留最近 50 条，
 * key = lumirss-enclosure-positions）；资源加载失败显示错误态 + 重试。 */

import { useEffect, useMemo, useRef, useState } from 'react'

import { isPlayableEnclosure } from '../lib/enclosure'

export { isPlayableEnclosure }
import { AlertCircle, Play, RotateCcw } from 'lucide-react'
import { Button } from './ui/Button'
import { cx } from './ui/cx'

export const ENCLOSURE_POSITIONS_KEY = 'lumirss-enclosure-positions'
export const ENCLOSURE_POSITIONS_LIMIT = 50
export const PLAYBACK_RATES = [0.75, 1, 1.25, 1.5, 2] as const
export type PlaybackRate = (typeof PLAYBACK_RATES)[number]

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

/** 单个附件播放器（显式开始；倍速；续播；错误态+重试）。 */
export function EnclosurePlayer({
  enclosure,
  entryRef,
  storage = typeof localStorage === 'undefined' ? null : localStorage,
}: {
  enclosure: EnclosureItem
  entryRef: string
  storage?: Storage | null
}) {
  const [started, setStarted] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [failed, setFailed] = useState(false)
  const [rate, setRate] = useState<PlaybackRate>(1)
  const mediaRef = useRef<HTMLAudioElement | HTMLVideoElement | null>(null)
  const positionId = useMemo(() => `${entryRef}|${enclosure.href}`, [entryRef, enclosure.href])
  const isVideo = (enclosure.type ?? '').toLowerCase().startsWith('video/')

  // 显式开始后：恢复上次位置 + 倍速 + 进度记录
  useEffect(() => {
    if (!started) return
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
    const onError = () => setFailed(true)
    media.addEventListener('loadedmetadata', onLoaded)
    media.addEventListener('timeupdate', onTimeUpdate)
    media.addEventListener('error', onError)
    media.playbackRate = rate
    return () => {
      media.removeEventListener('loadedmetadata', onLoaded)
      media.removeEventListener('timeupdate', onTimeUpdate)
      media.removeEventListener('error', onError)
    }
  }, [started, positionId, storage, rate, attempt])

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
          onClick={() => setStarted(true)}
          aria-label={`播放附件 ${enclosure.href}`}
        >
          <Play aria-hidden className="size-4" />
          播放
        </Button>
        <span className="min-w-0 flex-1 truncate text-xs text-[var(--lumi-text-secondary)]" title={enclosure.href}>
          {enclosure.type ?? '媒体附件'} · {enclosure.href}
        </span>
      </div>
    )
  }

  if (failed) {
    return (
      <div
        data-testid="enclosure-player"
        className="flex flex-wrap items-center gap-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-danger)]/30 bg-[var(--lumi-danger)]/10 px-3 py-2.5"
      >
        <AlertCircle aria-hidden className="size-4 shrink-0 text-[var(--lumi-danger)]" />
        <span className="min-w-0 flex-1 text-xs text-[var(--lumi-danger)]">
          附件加载失败，请检查网络后重试。
        </span>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => {
            setFailed(false)
            setAttempt((n) => n + 1)
          }}
        >
          <RotateCcw aria-hidden className="size-3.5" />
          重试
        </Button>
      </div>
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
